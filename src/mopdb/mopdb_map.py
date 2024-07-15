#!/usr/bin/env python
# Copyright 2023 ARC Centre of Excellence for Climate Extremes (CLEX)
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
# last updated 10/04/2024
#

import logging
import csv
import json
import lzma
import xarray as xr

from operator import itemgetter, attrgetter
from pathlib import Path
from itertools import compress
from importlib.resources import files as import_files

from mopdb.mopdb_class import FPattern, Variable
from mopdb.utils import *
from mopdb.mopdb_utils import (get_cell_methods, remove_duplicates,
    get_realm, check_realm_units, get_date_pattern)


def get_cmorname(conn, vobj, version):
    """Queries mapping table for cmip name given variable name as output
       by the model
    """
    mopdb_log = logging.getLogger('mopdb_log')
    sql = f"""SELECT cmor_var,model,cmor_table,frequency FROM mapping
        WHERE input_vars='{vobj.name}' and (calculation=''
        or calculation IS NULL)""" 
    results = query(conn, sql, first=False, logname='mopdb_log')
    names = list(x[0] for x in results) 
    tables = list(x[2] for x in results) 
    mopdb_log.debug(f"In get_cmorname query results: {results}")
    if len(names) == 0:
        vobj.cmor_var = ''
        vobj.cmor_table = ''
    elif len(names) == 1:
        vobj.cmor_var = names[0]
        vobj.cmor_table = tables[0]
    elif len(names) > 1:
        mopdb_log.debug(f"Found more than 1 definition for {vobj.name}:\n" +
                       f"{results}")
        match_found = False
        for r in results:
            if r[1] == version and r[3] == vobj.frequency:
                vobj.cmor_var, vobj.cmor_table = r[0], r[2]
                match_found = True
                break
        if not match_found:
            for r in results:
                if r[3] == vobj.frequency:
                    vobj.cmor_var, vobj.cmor_table = r[0], r[2]
                    match_found = True
                    break
        if not match_found:
            for r in results:
                if r[1] == version:
                    vobj.cmor_var, vobj.cmor_table = r[0], r[2]
                    match_found = True
                    break
        if not match_found:
            vobj.cmor_var = names[0]
            vobj.cmor_table = tables[0]
            mopdb_log.info(f"Found more than 1 definition for {vobj.name}:\n"+
                        f"{results}\n Using {vobj.cmor_var} from {vobj.cmor_table}")
    return vobj
        "mip_era": "",
        "Conventions": "CF-1.7 ACDD1.3"
    }
    return header

def get_file_frq(ds, fnext):
    """Return a dictionary with frequency for each time axis.

    Frequency is inferred by comparing interval between two consecutive
    timesteps with expected interval at a given frequency.
    Order time_axis so ones with only one step are last, so we can use 
    file frequency (interval_file) inferred from other time axes.
    This is called if there are more than one time axis in file 
    (usually only UM) or if frequency can be guessed from filename.
    """
    mopdb_log = logging.getLogger('mopdb_log')
    frq = {}
    int2frq = {'dec': 3652.0, 'yr': 365.0, 'mon': 30.0,
               'day': 1.0, '6hr': 0.25, '3hr': 0.125,
               '1hr': 0.041667, '30min': 0.020833, '10min': 0.006944}
    # retrieve all time axes
    time_axs = [d for d in ds.dims if 'time' in d]
    time_axs_len = set(len(ds[d]) for d in time_axs)
    time_axs.sort(key=lambda x: len(ds[x]), reverse=True)
    mopdb_log.debug(f"in get_file_frq, time_axs: {time_axs}")
    max_len = len(ds[time_axs[0]]) 
    # if all time axes have only 1 timestep we cannot infer frequency
    # so we open also next file but get only time axs
    if max_len == 1:
        dsnext = xr.open_dataset(fnext, decode_times = False)
        time_axs2 = [d for d in dsnext.dims if 'time' in d]
        ds = xr.concat([ds[time_axs], dsnext[time_axs2]], dim='time')
        time_axs = [d for d in ds.dims if 'time' in d]
        time_axs_len = set(len(ds[d]) for d in time_axs)
        time_axs.sort(key=lambda x: len(ds[x]), reverse=True)
    for t in time_axs: 
        mopdb_log.debug(f"len of time axis {t}: {len(ds[t])}")
        if len(ds[t]) > 1:
            interval = (ds[t][1]-ds[t][0]).values
            interval_file = (ds[t][-1] -ds[t][0]).values 
        else:
            interval = interval_file
        mopdb_log.debug(f"interval 2 timesteps for {t}: {interval}")
        for k,v in int2frq.items():
            if math.isclose(interval, v, rel_tol=0.05):
                frq[t] = k
                break
    return frq

def write_varlist(conn, indir, match, version, alias):
    """Based on model output files create a variable list and save it
       to a csv file. Main attributes needed to map output are provided
       for each variable
    """
    mopdb_log = logging.getLogger('mopdb_log')
    line_cols = ['name','cmor_var','units','dimensions','_frequency',
        '_realm','cell_methods','cmor_table','vtype','size',
        'nsteps','fpattern','long_name','standard_name']
    vobj_list = []
    fobj_list = []
    patterns = []
    files = FPattern.list_files(indir, match)
    mopdb_log.debug(f"Files after sorting: {files}")
    if alias == '':
        alias = 'mopdb'
    fname = f"varlist_{alias}.csv"
    fcsv = open(fname, 'w')
    fwriter = csv.writer(fcsv, delimiter=';')
    fwriter.writerow(["name", "cmor_var", "units", "dimensions",
        "frequency", "realm", "cell_methods", "cmor_table", "vtype",
        "size", "nsteps", "fpattern", "long_name", "standard_name"])
    for fpath in files:
        # get filename pattern until date match
        mopdb_log.debug(f"Filename: {fpath.name}")
        fpattern = fpath.name.split(match)[0]
        if fpattern in patterns:
            continue
        patterns.append(fpattern)
        fobj = FPattern(fpattern, Path(indir))
        #pattern_list = list_files(indir, f"{fpattern}*")
        nfiles = len(fobj.files) 
        mopdb_log.debug(f"File pattern, number of files: {fpattern}, {nfiles}")
        #fwriter.writerow([f"#{fpattern}"])
        # get attributes for the file variables
        ds = xr.open_dataset(str(fobj.files[0]), decode_times=False)
        coords = [c for c in ds.coords] + ['latitude_longitude']
        #pass next file in case of 1 timestep per file and no frq in name
        fnext = str(fobj.files[1])
        if fobj.frequency == 'NAfrq' or fobj.realm == 'atmos':
            frq_dict = get_file_frq(ds, fnext)
            # if only one frequency detected empty dict
            if len(frq_dict) == 1:
                fobj.frequency = frq_dict.popitem()[1]
            else:
                fobj.multiple_frq = True
                fobj.frequency = frq_dict['time']
        mopdb_log.debug(f"Multiple frq: {fobj.multiple_frq}")
        if fobj.realm == "NArealm":
            fobj.realm = get_realm(version, ds)
        pattern_var_list = []
        for vname in ds.variables:
            vobj = Variable(vname, fobj) 
            if vname not in coords and all(x not in vname for x in ['_bnds','_bounds']):
                v = ds[vname]
                mopdb_log.debug(f"Variable: {vobj.name}")
                # get size in bytes of grid for 1 timestep and number of timesteps
                vobj.size = v[0].nbytes
                vobj.nsteps = nfiles * v.shape[0]
                # assign time axis frequency if more than one is available
                if fobj.multiple_frq:
                    if 'time' in v.dims[0]:
                        vobj._frequency = frq_dict[v.dims[0]]
                    else:
                        mopdb_log.info(f"Could not detect frequency for variable: {v}")
                attrs = v.attrs
                vobj.cell_methods, frqmod = get_cell_methods(attrs, v.dims)
                vobj.frequency = vobj.frequency + frqmod
                mopdb_log.debug(f"Frequency var: {vobj.frequency}")
                # try to retrieve cmip name
                vobj = get_cmorname(conn, vobj, version)
                vobj.units = attrs.get('units', "")
                vobj.long_name = attrs.get('long_name', "")
                vobj.standard_name = attrs.get('standard_name', "")
                vobj.dimensions = " ".join(v.dims)
                vobj.vtype = v.dtype
                line = [attrgetter(k)(vobj) for k in line_cols]
                fwriter.writerow(line)
                vobj_list.append(vobj)
                pattern_var_list.append(vobj)
        fobj.varlist = pattern_var_list
        fobj_list.append(fobj)
        mopdb_log.info(f"Variable list for {fpattern} successfully written")
    fcsv.close()
    return  fname, vobj_list, fobj_list

def match_stdname(conn, row, stdn):
    """Returns an updated stdn list if finds one or more variables
    in cmorvar table that match the standard name passed as input.
    It also return a False/True found_match boolean.
    """
    mopdb_log = logging.getLogger('mopdb_log')
    found_match = False
    sql = f"""SELECT name FROM cmorvar where 
        standard_name='{row['standard_name']}'"""
    results = query(conn, sql, first=False, logname='mopdb_log')
    matches = [x[0] for x in results]
    if len(matches) > 0:
        stdn = add_var(stdn, row, tuple([matches]+['']*7), stdnm=True)
        found_match = True

    return stdn, found_match


def match_var(row, version, mode, conn, records):
    """Returns match for variable if found after looping
       variables already mapped in database
    Parameters

    """
    mopdb_log = logging.getLogger('mopdb_log')
    found_match = False
    # build sql query based on mode
    sql_base = f"""SELECT cmor_var,input_vars,calculation,frequency,
        realm,model,cmor_table,positive,units FROM mapping where 
        input_vars='{row['name']}'"""
    sql_frq = f" and frequency='{row['frequency']}'"
    sql_ver = f" and model='{version}'"
    if mode == 'full':
        sql = sql_base + sql_frq + sql_ver
    elif mode == 'no_frq':
        sql = sql_base + sql_ver
    elif mode == 'no_ver':
        sql = sql_base + sql_frq
    # execute query and process results
    result = query(conn, sql, first=False, logname='mopdb_log')
    mopdb_log.debug(f"match_var: {result}, sql: {sql[110:]}") 
    if result is not None and result != []:
        for x in result:
            mopdb_log.debug(f"match: {x}")
            records = add_var(records, row, x)
        found_match = True

    return records, found_match

def parse_vars(conn, rows, version):
    """Returns records of variables to include in template mapping file,
    a list of all stash variables + frequency available in model output
    and a list of variables already defined in db
 
    Parameters
    ----------
    conn : connection object
    rows : list(dict)
         list of variables to match
    version : str
        model version to use to match variables

    Returns
    -------
    stash_vars : list
        varname-frequency for each listed variable, varname is from model output
    """
    mopdb_log = logging.getLogger('mopdb_log')
    full = []
    no_ver = []
    no_frq = []
    stdn = []
    no_match = []
    stash_vars = []

    # looping through variables from file and attempt matches to db 
    for row in rows:
        if row['name'][0] == "#" or row['name'] == 'name':
            continue
        else:
            full, found = match_var(row, version, 'full', conn, full)
        # if no match, ignore model version first and then frequency 
        mopdb_log.debug(f"found perfect match: {found}")
        if not found:
            no_ver, found = match_var(row, version, 'no_ver', conn, no_ver)
            mopdb_log.debug(f"found no ver match: {found}")
        if not found:
            no_frq, found = match_var(row, version, 'no_frq', conn, no_frq)
            mopdb_log.debug(f"found no frq match: {found}")
        # make a last attempt to match using standard_name
        if not found:
            if row['standard_name'] != '':
                stdn, found = match_stdname(conn, row, stdn)
            mopdb_log.debug(f"found stdnm match: {found}")
        if not found:
            no_match = add_var(no_match, row, tuple([row['name']]+['']*8)) 
        stash_vars.append(f"{row['name']}-{row['frequency']}")

    return full, no_ver, no_frq, stdn, no_match, stash_vars 

def add_var(vlist, row, match, stdnm=False):
    """Add information from match to variable list and re-order
    fields so they correspond to final mapping output.

    Parameters
    match : tuple
        match values (cmor_var,input_vars,calculation,frequency,
        realm,model(version),cmor_table,positive,units)
    """
    mopdb_log = logging.getLogger('mopdb_log')
    # assign cmor_var from match and swap place with input_vars
    mopdb_log.debug(f"Assign cmor_var: {match}")
    mopdb_log.debug(f"initial row: {row}")
    var = row.copy() 
    var['cmor_var'] = match[0]
    var['input_vars'] = match[1]
    orig_name = var.pop('name')
    # assign realm from match
    var['realm'] = match[4] 
    # with stdn assign cmorvar and table if only 1 match returned
    # otherwise assign table from match
    if stdnm: 
        var['input_vars'] = orig_name
        if len(var['cmor_var']) == 1:
            cmor_var, table = var['cmor_var'][0].split("-")
            var['cmor_var'] = cmor_var
            var['cmor_table'] = table 
    else:
        var['cmor_table'] = match[6] 
    # add calculation, positive and version 
    var['calculation'] = match[2]
    var['positive'] = match[7]
    var['version'] = match[5] 
    # maybe we should override units here rather than in check_realm_units
    # if units missing get them from match
    if var['units'] is None or var['units'] == '':
        var['units'] = match[8]
    vlist.append(var)
    return vlist

def potential_vars(conn, rows, stash_vars, version):
    """Returns list of variables that can be potentially derived from
    model output.

    Loop across all model variables to match
    Select any mapping that contains the variable and if there's a calculation
    NB rows modified by add_row when assigning cmorname and positive values

    Parameters
    ----------
    conn : connection object
    rows : list(dict)
         list of variables to match
    stash_vars : list
        varname-frequency for each listed variable, varname is from model output
    version : str
        model version to use to match variables

    Returns
    -------
    """
    mopdb_log = logging.getLogger('mopdb_log')
    pot_full = [] 
    pot_part = []
    pot_varnames = set()
    for row in rows:
        sql = f"""SELECT cmor_var,input_vars,calculation,frequency,
            realm,model,cmor_table,positive,units FROM mapping 
            WHERE input_vars like '%{row['name']}%'"""
        results = query(conn, sql, first=False, logname='mopdb_log')
        mopdb_log.debug(f"In potential: var {row['name']}, db results {results}")
        for r in results:
            allinput = r[1].split(" ")
            mopdb_log.debug(f"{len(allinput)> 1}")
            mopdb_log.debug(all(f"{x}-{row['frequency']}" in stash_vars for x in allinput))
            if len(allinput) > 1 and all(f"{x}-{row['frequency']}" in stash_vars for x in allinput):
                # if both version and frequency of applied mapping match
                # consider this a full matching potential var 
                if r[5] == version and r[3] == row['frequency']:
                   pot_full = add_var(pot_full, row, r)
                else:
                    pot_part = add_var(pot_part, row, r)
                pot_varnames.add(r[0])
    return pot_full, pot_part, pot_varnames


def write_map_template(conn, parsed, alias):
    """Write mapping csv file template based on list of variables to define 

    Input varlist file order:
    name, cmor_var, units, dimensions, frequency, realm, cell_methods,
    cmor_table, vtype, size, nsteps, fpattern, long_name, standard_name
    Mapping db order:
    cmor_var, input_vars, calculation, units, dimensions, frequency, realm,
    cell_methods, positive, cmor_table, model, notes, origin 
        for pot vars + vtype, size, nsteps, fpattern
    Final template order:
    cmor_var, input_vars, calculation, units, dimensions, frequency, realm,
    cell_methods, positive, cmor_table, version, vtype, size, nsteps, fpattern,
    long_name, standard_name
    """ 

    mopdb_log = logging.getLogger('mopdb_log')
    full, no_ver, no_frq, stdn, no_match, pot_full, pot_part = parsed
    keys = ['cmor_var', 'input_vars', 'calculation', 'units',
            'dimensions', 'frequency', 'realm', 'cell_methods',
            'positive', 'cmor_table', 'version', 'vtype', 'size',
            'nsteps', 'fpattern', 'long_name', 'standard_name'] 

    with open(f"map_{alias}.csv", 'w') as fcsv:
        fwriter = csv.DictWriter(fcsv, keys, delimiter=';')
        write_vars(full, fwriter, keys, conn=conn)
        div = ("# Derived variables with matching version and " +
            "frequency: Use with caution!")
        write_vars(pot_full, fwriter, div, conn=conn)
        div = ("# Variables definitions coming from different " +
            "version")
        write_vars(no_ver, fwriter, div, conn=conn)
        div = ("# Variables with different frequency: Use with"
            + " caution!")
        write_vars(no_ver, fwriter, div, conn=conn)
        div = ("# Variables matched using standard_name: Use " +
            "with caution!")
        write_vars(stdn, fwriter, div, sortby='input_vars')
        div = "# Derived variables: Use with caution!"
        write_vars(pot_part, fwriter, div, conn=conn)
            #pot=True, conn=conn, sortby=0)
        div = "# Variables without mapping"
        write_vars(no_match, fwriter, div)
        mopdb_log.debug("Finished writing variables to mapping template")
        fcsv.close()
    return

def write_vars(vlist, fwriter, div, conn=None, sortby='cmor_var'):
    """
    """

    mopdb_log = logging.getLogger('mopdb_log')
    if len(vlist) > 0:
        if type(div) is str:
            divrow = {x:'' for x in vlist[0].keys()}
            divrow['cmor_var'] = div
        elif type(div) is list:
            divrow = {x:x for x in div}
        fwriter.writerow(divrow)
        for var in sorted(vlist, key=itemgetter(sortby)):
            if conn:
                var = check_realm_units(conn, var)
            fwriter.writerow(var)
    return

def map_variables(conn, rows, version):
    """
    """
    mopdb_log = logging.getLogger('mopdb_log')
    # return lists of fully/partially matching variables and stash_vars 
    # these are input_vars for calculation defined in already in mapping db
    full, no_ver, no_frq, stdn, no_match, stash_vars = parse_vars(conn, 
        rows, version)
    # remove duplicates from partially matched variables 
    no_ver = remove_duplicate(no_ver)
    no_frq = remove_duplicate(no_frq, strict=False)
    no_match = remove_duplicate(no_match, strict=False)
    # check if more derived variables can be added based on all
    # input_vars being available
    pot_full, pot_part, pot_varnames = potential_vars(conn, rows,
        stash_vars, version)
    # potential vars have always duplicates: 1 for each input_var
    pot_full = remove_duplicate(pot_full, strict=False)
    pot_part = remove_duplicate(pot_part, extra=pot_full, strict=False)
    mopdb_log.info(f"Derived variables: {pot_varnames}")
    return full, no_ver, no_frq, stdn, no_match, pot_full, pot_part 

def write_catalogue(conn, parsed, vobjs, fobjs, alias):
    """Write intake-esm catalogue and returns name
    """
    mopdb_log = logging.getLogger('mopdb_log')
    # read template json file 
    jfile = import_files('mopdata').joinpath('intake_cat_template.json')
    with open(jfile, 'r') as f:
        template = json.load(f)
    # write updated json to file
    for k,v in template.items():
        if type(v) == str:
            template[k] = v.replace("<experiment>", alias)
    jout = f"intake_{alias}.json"
    with open(jout, 'w') as f:
        json.dump(template, f, indent=4)
    # read template yaml file 
    yfile = import_files('mopdata').joinpath('intake_cat_template.yaml')
    with open(yfile, "r") as f:
        maincat = f.read()
    maincat = maincat.replace("<experiment>", alias)
    mopdb_log.debug("Opened intake template files")
    # write updated yaml to file
    yout = f"intake_{alias}.yaml"
    with open(yout, 'w') as f:
        f.writelines(maincat)
    # create a dictionary for each file to list
    lines = create_file_dict(fobjs, alias)
    # write csv file
    cols = [x['column_name'] for x in template['attributes']]
    cols = ['path'] + cols 
    csvname = template['catalog_file']
    with lzma.open(csvname, 'wt') as fcsv:
        fwriter = csv.DictWriter(fcsv, cols)
        fwriter.writeheader()
        for fd in lines:
            fwriter.writerow(fd)
        fcsv.close()
    return jout, csvname

def create_file_dict(fobjs, alias):
    """
    """
    mopdb_log = logging.getLogger('mopdb_log')
    lines = []
    for pat_obj in fobjs:
        var_list = [v.name for v in pat_obj.varlist]
        # set to remove '' duplicates 
        mapvar_list = list(set(v.cmor_var for v in pat_obj.varlist))
        mapvar_list.remove("")
        stnm_list = list(set(v.standard_name for v in pat_obj.varlist))
        stnm_list.remove("")
        base_dict = {'experiment': alias,
                     'realm': pat_obj.realm,
                     'frequency': pat_obj.frequency,
                     'variable': str(var_list),
                     'map_var': str(mapvar_list),
                     'standard_name': str(stnm_list)}
        # work out date_pattern in filename
        fname = pat_obj.files[0].name
        date_pattern = get_date_pattern(fname, pat_obj.fpattern)
        # add date and path for each file
        for fpath in pat_obj.files:
            f = fpath.name
            fd = base_dict.copy()
            fd['path'] = str(fpath)
            fd['date'] = ''.join(c for c in compress(f, date_pattern)) 
            lines.append(fd)
    return lines