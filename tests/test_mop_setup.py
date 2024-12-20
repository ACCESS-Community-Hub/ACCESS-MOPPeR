#!/usr/bin/env python
# Copyright 2024 ARC Centre of Excellence for Climate Extremes
# author: Paola Petrelli <paola.petrelli@utas.edu.au>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from importlib.resources import files as import_files
from pathlib import Path

def test_import_data():
    fpath = import_files('mopdata.cmor_tables').joinpath(
             "CMIP6_Amon.json")
    assert Path(fpath).exists()
    fpath = import_files('mopdata').joinpath("notes.yaml")
    assert Path(fpath).exists()
