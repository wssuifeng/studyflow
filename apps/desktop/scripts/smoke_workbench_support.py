"""Shared synthetic fixture loader for the browser/IPC smoke checks."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('studyflow_workbench_fixture',Path(__file__).with_name('smoke-workbench.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
ROOT=module.ROOT
WORKSPACE=module.WORKSPACE
service=module.service
engine=module.engine
server=module.server
database=module.database
plan=module.plan
courses=module.courses
url=module.url
