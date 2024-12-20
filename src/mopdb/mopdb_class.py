#!/usr/bin/env python
# Copyright 2024 ARC Centre of Excellence for Climate Extremes (CLEX)
# Author: Paola Petrelli <paola.petrelli@utas.edu.au> for CLEX
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
#
# contact: paola.petrelli@utas.edu.au
#
# last updated 03/10/2024

from pathlib import Path
from operator import itemgetter
import re

class FPattern():
    """This class represent a file pattern with a set list of variables
       its attributes represents features of the variables which are shared.
    """ 

    def __init__(self, fpattern: str, fpath: Path | None) -> None:
        self.fpattern = fpattern
        self.fpath = fpath
        self.files = self.get_files() 
        self.realm =  self.get_realm()
        self.frequency = self.get_frequency() 
        self.version = ''
        self.multiple_frq = False
        self.varlist = []

    def get_frequency(self):
        frequency = 'NAfrq'
        if len(self.files) > 0 and self.realm != 'NArealm':
            fname = str(self.files[0])
            if self.realm == 'atmos':
                fbits = fname.split("_")
                frequency = fbits[-1].replace(".nc", "")
            elif self.realm == 'ocean':
                if any(x in fname for x in ['scalar', 'month']):
                    frequency = 'mon'
                elif 'daily' in fname:
                    frequency = 'day'
            elif self.realm == 'seaIce':
                if '_m.' in fname:
                    frequency = 'mon'
                elif '_d.' in fname:
                    frequency = 'day'
        return frequency

    def get_realm(self):
        realm = 'NArealm'
        if self.fpath is not None:
            realm = next((x for x in ['atmos', 'ocean', 'ice', 'ocn','atm']
                if x in self.fpath.parts), 'NArealm')
        fix_realm = {'atm': 'atmos', 'ice': 'seaIce', 'ocn': 'ocean'}
        if realm in fix_realm.keys():
            realm = fix_realm[realm]
        return realm

    def get_files(self):
        if self.fpath is None:
            files = []
        else:
            files = self.list_files(self.fpath, self.fpattern)
        return files

    @staticmethod
    def list_files(indir, match):
        """Returns list of files matching input directory and match"""
        files = [x for x in Path(indir).rglob(f"*{match}*")
            if x.is_file() and  '.nc' in str(x)]
        files.sort(key=lambda x:x.name)
        # if files use month labels sort by month
        files = FPattern.order_months(files, match)
        return files


    @staticmethod
    def order_months(files, match):
        """If files use month labels sort by month. This can be removed
        once using only sensible dates.
        
        Check first file after removing pattern (match). Then build dict
        assigning a numeric month version to each file. Finally sort by
        these values and save as list.
        """
        mlabels = {'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
            'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
            'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'}
        newlist = {}
        for f in files:
            short = f.name.replace(match,'')
            basedir = f.parent
            res = re.search('|'.join(mlabels.keys()), short)
            if res is not None:
                mon = res.group(0)
            #if any(x in short for x in mlabels.keys()):
            #    for k,v in mlabels.items():
            #        if k in short:
                newlist[f] = str(f).replace(mon,mlabels[mon])
            else:
                newlist[f] = str(f)
        sorted_list = sorted(newlist.items(), key=itemgetter(1))
        files = [Path(x[0]) for x in sorted_list]
        return files


class Variable():
    """This class represent a single variable with attributes derived from file
       and the one added by mapping.
    """ 

    def __init__(self, varname: str, fobj: FPattern):
        self.name = varname
        # path object
        self.fpattern = fobj.fpattern
        # mapping attributes
        self._frequency = fobj.frequency 
        self._realm = fobj.realm
        self.cmor_var = '' 
        self.cmor_table = '' 
        #self.input_vars = varname 
        self.calculation = '' 
        self.version = fobj.version
        self.match = False
        # descriptive attributes
        self.units = '' 
        self.dimensions = '' 
        self.cell_methods = ''
        self.positive = ''
        self.long_name = '' 
        self.standard_name = '' 
        # type and size attributes
        self.vtype = ''
        self.size = 0
        self.nsteps = 0


    @property
    def frequency(self):
        return self._frequency


    @frequency.setter
    def frequency(self, value):
        value = value.replace('hPt', 'hrPt')
        if not any(x in value for x in 
            ['fx', 'min', 'hr', 'day', 'mon', 'yr']):
            value = 'NAfrq' 
        self._frequency = value


    @property
    def realm(self):
        return self._realm

    @realm.setter
    def realm(self, value):
        if not any(x in value for x in 
            ['atmos', 'seaIce', 'ocean', 'land', 'landIce']):
            value = 'NArealm' 
        self.realm = value

    def get_match(self):
        """Returns the attributes that mimic
        a database match"""
        if self.cmor_var != '':
            cmor_var = self.cmor_var
        else:
            cmor_var = self.name
        match = (cmor_var, self.name, '', self.frequency,
            self.realm, self.version, '', self.positive,
            self.units, self.dimensions)
        return match


class MapVariable():
    """This class represent a mapping for variable 
       It's similar but from a cmor_name point of view
    """ 

    def __init__(self, match: list, vobj: Variable):
        # path object
        self.fpattern = vobj.fpattern
        # mapping attributes
        self.frequency = vobj.frequency 
        self.realm = match[4]
        self.cmor_var = match[0] 
        self.cmor_table = match[6] 
        self.input_vars = match[1] 
        self.calculation = match[2] 
        self.version = match[5]
        # could change this to nomatch found or 
        # kind of match
        self.match = True
        # descriptive attributes
        self.units = vobj.units 
        if self.units == '':
            self.units = match[8]
        self.dimensions = vobj.dimensions 
        self.axes = match[9] 
        self.cell_methods = vobj.cell_methods
        self.positive = match[7]
        self.long_name = vobj.long_name 
        self.standard_name = vobj.standard_name
        # type and size attributes
        self.vtype = vobj.vtype
        self.size = vobj.size
        self.nsteps = vobj.nsteps

    def attrs(self):
        attrs = [] 
        for k in self.__dict__.keys():
            if k not in ['match']:
                attrs.append(k)
        return attrs
