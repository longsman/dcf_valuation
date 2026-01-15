from functools import reduce
from typing import Dict, List, Optional

import pyspark.sql.functions as f
from delta._typing import ColumnMapping
from delta.tables import DeltaTable
from pydantic import BaseModel
from pyspark.errors.exceptions.base import AnalysisException
from pyspark.sql import DataFrame
from pyspark.sql.window import Window

from ..enums import TableFormat
from ..util import matches_any_pattern
from .core import BaseConsumer, consumer


class MetaColumnsProcessor(BaseModel):
    id_col: str = '_id'
    footprint_col: str = '_footprint'

    def get_meta_col_list(self) -> List[str]:
        return [self.id_col, self.footprint_col]

    def apply(self, df: DataFrame) -> DataFrame:
        lower_cols = [c.lower() for c in df.columns]
        return (
            df
            .withColumn(self.footprint_col, f.struct(
               (f.col(self.id_col) if self.id_col in lower_cols else f.lit(None).cast('string')).alias('upstream_id'),
                f.current_timestamp().alias('create_ts'),
                f.current_timestamp().alias('modify_ts')
            ))
            .select(
                f.expr('uuid()').alias(self.id_col),
                *[c for c in lower_cols if c not in (self.id_col, self.footprint_col)],
                f.col(self.footprint_col)
            )
        )


@consumer
class SaveAsTable(BaseConsumer):
    table: str
    format: TableFormat = TableFormat.DELTA
    partition_by: Optional[List[str]] = None
    options: Optional[Dict[str, str]] = None

    def consume(self, df: DataFrame, _: Optional[int] = None) -> None:
        meta = MetaColumnsProcessor()
        writer = meta.apply(df).write.format(self.format.value)
        if self.partition_by:
            writer.partitionBy(self.partition_by)
        if self.options:
            writer.options(**self.options)
        writer.saveAsTable(self.table)


@consumer
class MergeTable(BaseConsumer):
    table: str
    key_columns: Optional[List[str]] = None
    ignore_columns: Optional[List[str]] = None
    drop_columns: Optional[List[str]] = None
    delete_condition: str = 'False'
    delete_when_not_matched_by_source: bool = False
    event_order_expression_list: Optional[List[str]] = None
    event_order_is_absolute: bool = False
    columns_ignore_case: bool = True
    partition_by: Optional[List[str]] = None

    def consume(self, df: DataFrame, _: Optional[int] = None) -> None:
        meta = MetaColumnsProcessor()
        df = meta.apply(df)
        resolved_ignore_columns = [
            c for c in df.columns
            if matches_any_pattern(c, self.ignore_columns or ['_.*?'], self.columns_ignore_case)
        ] + meta.get_meta_col_list()

        resolved_key_columns = (
            [c for c in df.columns if not matches_any_pattern(c, resolved_ignore_columns, self.columns_ignore_case)]
            if not self.key_columns
            else [c for c in df.columns if matches_any_pattern(c, self.key_columns, self.columns_ignore_case)]
        )

        # Because the write strategy is MERGE, we often need to ensure only a single record exists in the table per key.
        # If `event_order_*` fields are provided, perform extra processing to eliminate "older" versions of records
        # when multiple records (events) exist per key.
        if self.event_order_expression_list:
            converted = []
            for ex in self.event_order_expression_list:
                parts = ex.split(' ')
                if len(parts) == 1 or parts[-1].lower() == 'asc':
                    converted.append(f.asc(parts[0]))
                else:
                    converted.append(f.desc(parts[0]))
            df = (
                df.withColumn('_recency', f.row_number().over(
                    Window.partitionBy(resolved_key_columns)
                    .orderBy(converted)
                ))
                .filter(f.col('_recency') == 1)
                .drop('_recency')
            )

        try:
            dt = DeltaTable.forName(df.sparkSession, self.table)
        except AnalysisException:
            df.write.saveAsTable(self.table)
            return

        match_condition = reduce(
            lambda a, b: a & b,
            [
                f.col(f'inc.{c}').eqNullSafe(f.col(f'tab.{c}'))
                for c in resolved_key_columns
            ]
        )
        merge = dt.alias('tab').merge(df.alias('inc'), match_condition)

        # Deletes
        merge = merge.whenMatchedDelete(f.expr(self.delete_condition))

        # Updates
        if self.key_columns:
            update_condition = reduce(
                lambda a, b: a | b,
                [
                    ~f.col(f'inc.{c}').eqNullSafe(f.col(f'tab.{c}'))
                    for c in df.columns
                    if not matches_any_pattern(c, resolved_key_columns + resolved_ignore_columns, self.columns_ignore_case)
                ]
            )
            update_set_expr: ColumnMapping = {
                c: f.col(f'inc.{c}')
                for c in resolved_key_columns
            }
            merge = merge.whenMatchedUpdate(set=update_set_expr, condition=update_condition)
        merge = merge.whenMatchedUpdate(set={})  # Do nothing with matched records that have no changes

        # Inserts
        insert_set_expr: ColumnMapping = {
            c: f.col(f'inc.{c}')
            for c in df.columns
            if not matches_any_pattern(c, self.drop_columns or [], self.columns_ignore_case)
        }
        merge = merge.whenNotMatchedInsert(values=insert_set_expr, condition=~f.expr(self.delete_condition))

        # In the event we have a full-snapshot input and we should delete missing keys..
        if self.delete_when_not_matched_by_source:
            merge.whenNotMatchedBySourceDelete()

        merge.execute()
