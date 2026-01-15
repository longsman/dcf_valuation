import csv
import csv
from pathlib import Path
from typing import Any, Dict, Optional

from pyspark.sql import DataFrame
import pyspark.sql.types as t

from superwind.enums import ExecutionMode
from superwind.exceptions import StreamModeNotSupportedError
from superwind.util import get_spark_session
from superwind.producers.core import BaseProducer, producer


@producer
class ReadCSV(BaseProducer):
    """Read a small CSV file packaged with the wheel.

    This is intentionally implemented as a driver-side read (Python csv module)
    followed by `spark.createDataFrame`, to avoid relying on the packaged file
    path being consistent across executors.
    """

    path: str
    options: Dict[str, str] = {}
    encoding: str = "utf-8"

    def produce(self, mode: ExecutionMode = ExecutionMode.BATCH) -> DataFrame:
        if ExecutionMode(mode) == ExecutionMode.STREAMING:
            raise StreamModeNotSupportedError(
                "`ReadCSV` can only operate in BATCH mode."
            )

        # Some callers may pass file: URIs.
        csv_path = self.path
        if csv_path.startswith("file:"):
            csv_path = csv_path[len("file:") :]

        path_obj = Path(csv_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"CSV file does not exist: {csv_path}")

        header_opt = str(self.options.get("header", "true")).lower() == "true"
        delimiter = self.options.get("sep") or self.options.get("delimiter") or ","

        with path_obj.open("r", encoding=self.encoding, newline="") as fh:
            reader = csv.reader(fh, delimiter=delimiter)
            rows = list(reader)

        spark = get_spark_session()
        if not rows:
            # empty dataset
            return spark.createDataFrame([], schema=t.StructType([]))

        if header_opt:
            columns = [c.strip() for c in rows[0]]
            data_rows = rows[1:]
        else:
            columns = [f"_c{i}" for i in range(len(rows[0]))]
            data_rows = rows

        schema = t.StructType([t.StructField(c, t.StringType(), True) for c in columns])

        def normalize(v: Any) -> Optional[str]:
            if v is None:
                return None
            s = str(v)
            if s.strip() == "":
                return None
            return s

        records = [
            {
                columns[i]: normalize(row[i]) if i < len(row) else None
                for i in range(len(columns))
            }
            for row in data_rows
            if row
        ]

        return spark.createDataFrame(records, schema=schema)


@producer
class ExecSQL(BaseProducer):
    """Run a SQL query and return the resulting DataFrame."""

    sql_query: Optional[str] = None
    sql_file: Optional[str] = None

    def produce(self, mode: ExecutionMode = ExecutionMode.BATCH) -> DataFrame:
        if ExecutionMode(mode) == ExecutionMode.STREAMING:
            raise StreamModeNotSupportedError(
                "`ExecSQL` can only operate in BATCH mode."
            )

        if self.sql_query and self.sql_file:
            raise ValueError("Only one of `sql_query` or `sql_file` may be provided.")
        if not self.sql_query and not self.sql_file:
            raise ValueError("Either `sql_query` or `sql_file` must be provided.")

        query = self.sql_query
        if self.sql_file:
            query = Path(self.sql_file).read_text(encoding="utf-8")

        return get_spark_session().sql(query)  # type: ignore[arg-type]
