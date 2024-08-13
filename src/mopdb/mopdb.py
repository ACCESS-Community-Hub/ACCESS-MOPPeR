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
# last updated 08/04/2024

import click
import logging
import sys
import json

from importlib.resources import files as import_files
from pathlib import Path

from mopdb.mopdb_utils import (mapping_sql, cmorvar_sql, read_map,
    read_map_app4, create_table, write_cmor_table, update_db) 
from mopdb.utils import (config_log, db_connect, query, delete_record)
from mopdb.mopdb_map import (write_varlist, write_map_template,
    write_catalogue, map_variables, load_vars, get_map_obj)

def mopdb_catch():
    """
    """
    debug_logger = logging.getLogger('app_debug')
    debug_logger.setLevel(logging.CRITICAL)
    try:
        mopdb()
    except Exception as e:
        click.echo('ERROR: %s'%e)
        debug_logger.exception(e)
        sys.exit(1)


def require_date(ctx, param, value):
    """Changes match option in template command from optional to
    required if fpath is a directory.
    """
    names = []
    for i in range(len(ctx.command.params)):
        names.append(ctx.command.params[i].name)
    idx = names.index('match')
    if Path(value).is_dir() and 'filelist' not in names:
        ctx.command.params[idx].required = True
    return value


def db_args(f):
    """Define database click options
    """
    constraints = [
        click.option('--fname', '-f', type=str, required=True,
            help='Input file: used to update db table (mapping/cmor)'),
        click.option('--dbname', type=str, required=False, default='default',
            help='Database relative path by default is package access.db'),
        click.option('--alias', '-a', type=str, required=False, default='',
            help='Table alias to track definitions origin in cmorvar table.')]
    for c in reversed(constraints):
        f = c(f)
    return f


def map_args(f):
    """Define mapping click options for varlist, template, intake
    commands
    """
    constraints = [
        click.option('--fpath', '-f', type=str, required=True,
            callback=require_date,
            help=("""Model output files path. For 'template'
              command can also be file generated by varlist step""")),
        click.option('--match', '-m', type=str, required=False,
            help=("""String to match output files. Most often
                the timestamp from one of the output files""")),
        click.option('--version', '-v', required=True,
            type=click.Choice(['ESM1.5', 'CM2', 'AUS2200', 'OM2']),
            show_default=True,
            help="ACCESS version currently only CM2, ESM1.5, AUS2200, OM2"),
        click.option('--dbname', type=str, required=False, default='default',
            help="Database relative path by default is package access.db"),
        click.option('--alias', '-a', type=str, required=False, default='',
            help="""Alias to use to keep track of variable definition origin.
                 If none passed uses input filename""")]
    for c in reversed(constraints):
        f = c(f)
    return f


@click.group(context_settings=dict(help_option_names=['-h', '--help']))
@click.option('--debug', is_flag=True, default=False,
               help="Show debug info")
@click.pass_context
def mopdb(ctx, debug):
    """Main group command, initialises log and context object
    """
    ctx.obj={}
    # set up a default value for flow if none selected for logging
    ctx.obj['debug'] = debug
    #mopdb_log = config_log(debug, logname='mopdb_log')


@mopdb.command(name='check')
@click.option('--dbname', type=str, required=False, default='default',
            help='Database relative path by default is package access.db')
@click.pass_context
def check_cmor(ctx, dbname):
    """Prints list of cmor_var defined in mapping table but not in
    cmorvar table.


    Parameters
    ----------
    ctx : obj
        Click context object
    dbname : str
        Database relative path (default is data/access.db)
    """
    mopdb_log = logging.getLogger('mopdb_log')
    # connect to db, this will create one if not existing
    if dbname == 'default':
        dbname = import_files('mopdata').joinpath('access.db')
    conn = db_connect(dbname, logname='mopdb_log')
    # get list of variables already in db
    sql = 'SELECT name, out_name FROM cmorvar'
    results = query(conn, sql, first=False, logname='mopdb_log')
    # first set is the actual cmip variable name 
    # second set is the name used in tables to distinguish different dims/freq
    # original maps files use the second style
    cmor_vars = set(x[1] for x in results)
    cmor_vars2 = set(x[0].split('-')[0] for x in results)
    cmor_vars.update(cmor_vars2)

    sql = 'SELECT cmor_var FROM mapping'
    results = query(conn, sql, first=False, logname='mopdb_log')
    map_vars = [x[0] for x in results]
    missing = set(map_vars) - set(cmor_vars)
    mopdb_log.info("Variables not yet defined in cmorvar table:")
    for v in missing:
        mopdb_log.info(f"{v}")
    conn.close()
    return


@mopdb.command(name='table')
@db_args
@click.option('--label', '-l', required=False, default='CMIP6',
    type=click.Choice(['CMIP6', 'AUS2200', 'CM2', 'OM2']),
    show_default=True,
    help='''Label indicating origin of CMOR variable definitions. 
    Currently only CMIP6, AUS2200, CM2 and OM2''')
@click.pass_context
def cmor_table(ctx, dbname, fname, alias, label):
    """Create CMIP style table containing new variable definitions
    fname  from output to extract cmor_var, frequency, realm 
    If these var/freq/realm/dims combs don't exist in cmorvar add var to table.
    `alias` here act as the new table name.

    Parameters
    ----------
    ctx : obj
        Click context object
    dbname : str
        Database relative path (default is data/access.db)
    fname : str
        Mapping file??? 
    alias : str
           ??? it is used so what's ahppenw hen not passed?
    label : str
        Label indicating preferred cmor variable definitions 
    """
    mopdb_log = logging.getLogger('mopdb_log')
    # connect to db, this will create one if not existing
    if dbname == 'default':
        dbname = import_files('mopdata').joinpath('access.db')
    conn = db_connect(dbname, logname='mopdb_log')
    # get list of variables already in db
    sql = "SELECT out_name, frequency, modeling_realm FROM cmorvar"
    results = query(conn, sql, first=False, logname='mopdb_log')
    # cmor_vars is the actual cmip variable name 
    # this sometime differs from name used in tables tohat can distinguish different dims/freq
    cmor_vars = set(x[0] for x in results)
    # read variable list from map_ file
    vlist = read_map(fname, alias)
    # extract cmor_var,units,dimensions,frequency,realm,cell_methods
    var_list = []
    for v in vlist[1:]:
        #vid = (v[0], v[5], v[6])
        # This was adding variables to the table just if they didn't exists in other tables
        if v[0][:4] != 'fld_':
            if v[0] not in cmor_vars:
                mopdb_log.warning(f"Variable {v[0]} not defined in cmorvar table")
            else:
                
                sql = f"SELECT * FROM cmorvar WHERE out_name='{v[0]}'"
                records = query(conn, sql, first=False, logname='mopdb_log')
                record = records[0]
                if len(records) > 1:
                    for r in records:
                        if f"-{label}_" in r[0]:
                            record = r
                            break
                definition = list(record)
                #definition[0] = f"{v[0]}-{alias}"
                definition[0] = v[0].replace('_', '-')
                definition[1] = v[5]
                definition[2] = v[6]
                # if units are different print warning!
                if v[3] != record[4]:
                    mopdb_log.warning(f"Variable {v[0]} units orig/table are different: {v[3]}/{record[4]}")
                if v[7] != '' and v[7] != record[5]:
                    mopdb_log.warning(f"Variable {v[0]} cell_methods orig/table are different: {v[7]}/{record[5]}")
                if len(v[4].split()) != len(record[9].split()):
                    mopdb_log.warning(f"Variable {v[0]} number of dims orig/table are different: {v[4]}/{record[9]}")
                var_list.append(definition)
    write_cmor_table(var_list, alias)
    conn.close()
    return


@mopdb.command(name='cmor')
@db_args
@click.pass_context
def update_cmor(ctx, dbname, fname, alias):
    """Open/create database and create/update cmorvar table. Table is 
    populated with data passed via input json file.
    Input json file is written in same style as CMOR CMIP6 tables.

    Parameters
    ----------
    ctx : obj
        Click context object
    dbname : str
        Database relative path (default is data/access.db)
    fname : str
        Name of json input file with records to add
    alias : str
        Indicates origin of records to add, if '' (default) json
        filename base is used instead

    Returns
    -------
    """

    mopdb_log = logging.getLogger('mopdb_log')
    if alias == '':
        alias = fname.split("/")[-1]
        alias = alias.replace('.json', '')
    mopdb_log.info(f"Adding {alias} to variable name to track origin")
    # connect to db, this will create one if not existing
    dbcentral = import_files('mopdata').joinpath('access.db')
    if dbname in [dbcentral, 'default']:
        mopdb_log.error("The package database cannot be updated")
        sys.exit()
    conn = db_connect(dbname, logname='mopdb_log')
    # create table if not existing
    table_sql = cmorvar_sql()
    create_table(conn, table_sql, logname='mopdb_log')
    # get list of variables already in db in debug mode
    if ctx.obj['debug']:
        sql = 'SELECT name FROM cmorvar'
        results = query(conn, sql, first=False, logname='mopdb_log')
        existing_vars = [x[0] for x in results]
        mopdb_log.debug(f"Variables already in db: {existing_vars}")

    # read list of vars from file
    with open(fname, 'r') as fj:
         vardict = json.load(fj)
    row_dict = vardict['variable_entry']
    vars_list = []
    for name,row in row_dict.items():
    # alter the name so it reflects also its origin
        name = f"{name}-{alias}" 
        values = [x for x in row.values()]
        # check if flag attrs present if not add them
        if 'flag_values' not in row.keys():
            values = values[:-2] + ['',''] + values[-2:]
        vars_list.append(tuple([name] + values))
    mopdb_log.debug(f"Variables list: {vars_list}")
    # check that all tuples have len == 19
    for r in vars_list:
        if len(r) != 19:
            mopdb_log.error(r)
            sys.exit()
    # insert new vars and update existing ones
    update_db(conn, 'cmorvar', vars_list)
    conn.close()

    return


@mopdb.command(name='template')
@map_args
@click.pass_context
def map_template(ctx, fpath, match, dbname, version, alias):
    """Writes a template of mapping file needed to run setup.
       First opens database and check if variables match any in
       mapping table. If not tries to partially match them.

    It can get as input the directory containing the output in
    which case it will first call write_varlist()
    or the file output of the same if already available.

    Parameters
    ----------
    ctx : obj
        Click context object
    fpath : str
        Path of csv input file with output variables to map or
        of directory containing output files to scan
    match : str
        Date or other string to match to individuate one file per type
    dbname : str
        Database relative path (default is data/access.db)
    version : str
        Version of ACCESS model used to generate variables
    alias : str
        Indicates origin of records to add, if '' csv filename
        base is used instead

    Returns
    -------
    """
    mopdb_log = logging.getLogger('mopdb_log')
    # connect to db, this will create one if not existing
    if dbname == 'default':
        dbname = import_files('mopdata').joinpath('access.db')
    conn = db_connect(dbname, logname='mopdb_log')
    # work out if fpath is varlist or path to output
    fpath = Path(fpath)
    if fpath.is_file():
        map_file, vobjs, fobjs = load_vars(fpath)
        fname = fpath.name
        mopdb_log.debug(f"Imported {len(vobjs)} objects from file {fpath}")
        mopdb_log.debug(f"Is mapping file? {map_file}")
    else:
        mopdb_log.debug(f"Calling write_varlist() from template: {fpath}")
        fname, vobjs, fobjs = write_varlist(conn, fpath, match, version, alias)
    if alias == '':
        alias = fname.split(".")[0]
    parsed = map_variables(conn, vobjs, version)
    # potential vars have always duplicates: 1 for each input_var
    write_map_template(conn, parsed, alias)
    conn.close()
    return


@mopdb.command(name='intake')
@map_args
@click.option('--filelist','-fl', type=str, required=False, default=None,
            help='Map or varlist csv file relative path')
@click.pass_context
def write_intake(ctx, fpath, match, filelist, dbname, version, alias):
    """Writes an intake-esm catalogue.

    It can get as input the directory containing the output in
    which case it will first call write_varlist() (varlist command)
    or the file output of the same if already available.

    Parameters
    ----------
    ctx : obj
        Click context object
    fpath : str
        Path of directory containing output files to scan
    match : str
        Date or other string to match to individuate one file per type
    filelist : str
        Map or varlist csv file path, optional (default is None)
    dbname : str
        Database relative path (default is data/access.db)
    version : str
        Version of ACCESS model used to generate variables
    alias : str
        Indicates origin of records to add, if '' csv filename
        base is used instead

    Returns
    -------
    """
    mopdb_log = logging.getLogger('mopdb_log')
    # connect to db, check first if db exists or exit 
    if dbname == 'default':
        dbname = import_files('mopdata').joinpath('access.db')
    conn = db_connect(dbname, logname='mopdb_log')
    # work out if fpath is varlist or path to output
    fpath = Path(fpath)
    if fpath.is_file():
        mopdb_log.error(f"""   {fpath} 
        should be absolute or relative path to model output.
        To pass a varlist or map file use --filelist/-f""")
    elif filelist is None:
        mopdb_log.debug(f"Calling write_varlist() from intake: {fpath}")
        fname, vobjs, fobjs = write_varlist(conn, fpath, match, version, alias)
        map_file = False
    else:
        flist = Path(filelist)
        fname = flist.name
        map_file, vobjs, fobjs = load_vars(flist, indir=fpath)
    if alias == '':
        alias = fname.split(".")[0]
    # return lists of fully/partially matching variables and stash_vars 
    # these are input_vars for calculation defined in already in mapping db
    if map_file is False:
        parsed = map_variables(conn, vobjs, version)
        vobjs = get_map_obj(parsed)
        write_map_template(conn, parsed, alias)
    # potential vars have always duplicates: 1 for each input_var
    cat_name, fcsv = write_catalogue(conn, vobjs, fobjs, alias)
    mopdb_log.info(f"""Intake-esm and intake catalogues written to
    {cat_name} and {cat_name.replace('json','yaml')}. File list saved to {fcsv}""")
    conn.close()
    return None


@mopdb.command(name='map')
@db_args
@click.pass_context
def update_map(ctx, dbname, fname, alias):
    """Open database and create/update populating with rows
       mapping file passed as input
       alias indicates origin: if old style use 'app4'

    Parameters
    ----------
    ctx : obj
        Click context object
    dbname : str
        Database relative path (default is data/access.db)
    fname : str
        Name of csv input file with mapping records
    alias : str
        Indicates origin of records to add, if '' csv filename
        base is used instead

    Returns
    -------
    """
    mopdb_log = logging.getLogger('mopdb_log')
    # connect to db, this will create one if not existing
    dbcentral = import_files('mopdata').joinpath('access.db')
    if dbname in [dbcentral, 'default']:
        mopdb_log.error("The package database cannot be updated")
        sys.exit()
    conn = db_connect(dbname, logname='mopdb_log')
    # create table if not existing
    table_sql = mapping_sql()
    create_table(conn, table_sql, logname='mopdb_log')
    # get list of variables already in db in debug mode
    if ctx.obj['debug']:
        sql = 'SELECT cmor_var FROM mapping'
        results = query(conn, sql, first=False, logname='mopdb_log')
        existing_vars = [x[0] for x in results]
        mopdb_log.debug(f"Variables already in db: {existing_vars}")
    # read list of vars from file
    if alias == 'app4':
        var_list = read_map_app4(fname)
    else:
        var_list = read_map(fname, alias)
    # update mapping table
    update_db(conn, 'mapping', var_list)
    conn.close()
    return None


    return None


@mopdb.command(name='varlist')
@map_args
@click.pass_context
def model_vars(ctx, fpath, match, dbname, version, alias):
    """Read variables from model output
       opens one file for each kind, save variable list as csv file

    Parameters
    ----------
    ctx : obj
        Click context object
    fpath : str
        Path for model output files
    match : str
        Date or other string to match to individuate one file per type
    dbname : str
        Database relative path (default is data/access.db)
    version : str
        Version of ACCESS model to use as preferred mapping
    alias : str
        Used for output filename: 'varlist_<alias>'. If '', 
        'varlist_mopdb' is used instead

    Returns
    -------
    """
    # connect to db, check first if db exists or exit 
    if dbname == 'default':
        dbname = import_files('mopdata').joinpath('access.db')
    conn = db_connect(dbname, logname='mopdb_log')
    #mopdb_log = logging.getLogger('mopdb_log')
    fname, vobjs, fobjs = write_varlist(conn, fpath, match, version, alias)
    conn.close()
    return None


@mopdb.command(name='del')
@click.option('--dbname', type=str, required=True,
    help='Database relative path')
@click.option('--table', '-t', type=str, required=True,
    help='DB table to remove records from')
@click.option('--pair', '-p', type=(str, str), required=True,
    multiple=True,
    help='''Pair of "column value" to select record/s to delete.
        At least one is required, can be passed multiple times''')
@click.pass_context
def remove_record(ctx, dbname, table, pair):
    """Selects and removes records based on constraints
    passed as input

    Parameters
    ----------
    ctx : obj
        Click context object
    dbname : str
        Database relative path
    pair : list[tuple(str, str)]
        list of all the column:value tuples to be used to select
        record/s to delete

    Returns
    -------
    """
    mopdb_log = logging.getLogger('mopdb_log')
    # connect to db, this will create one if not existing
    dbcentral = import_files('mopdata').joinpath('access.db')
    if dbname == dbcentral:
        mopdb_log.error("The package database cannot be updated")
        sys.exit()
    conn = db_connect(dbname)
    conn = db_connect(dbname, logname='mopdb_log')
    # set which columns to show based on table
    if table == 'cmorvar':
        col = "name"
    elif table == 'mapping':
        col = "cmor_var,frequency,realm,cmor_table" 
    # select, confirm, delete record/s 
    delete_record(conn, table, col, pair, logname='mopdb_log')
    conn.close()
    return
