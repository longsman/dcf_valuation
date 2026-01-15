# Databricks notebook source
import importlib
from pyspark.sql import SparkSession
from superwind.definition.yaml import YAMLPipelineDefinition

dbutils = importlib.import_module('pyspark.dbutils').DBUtils(SparkSession.builder.getOrCreate())
parser = YAMLPipelineDefinition()
pdef = parser.load(dbutils.notebook.entry_point.getCurrentBindings()['yaml_file'])
print(parser.dumps(pdef))
pdef.run()