#!/usr/bin/env python
# Copyright 2023 ARC Centre of Excellence for Climate Extremes
# author: Paola Petrelli <paola.petrelli@utas.edu.au>
# author: Sam Green <sam.green@unsw.edu.au>
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
# This is the ACCESS Model Output Post Processor, derived from the APP4
# originally written for CMIP5 by Peter Uhe and dapted for CMIP6 by Chloe Mackallah
# ( https://doi.org/10.5281/zenodo.7703469 )
#
# last updated 10/10/2024
#
# This file contains a collection of functions to calculate ocean derived variables
# from ACCESS model output.
# Initial functions' definitions were based on APP4 modified to work with Xarray.
#
# To propose new calculations and/or update to existing ones see documentation:
#
# and open a new issue on github.


import click
import xarray as xr
import os
import json 
import numpy as np
import dask
import logging
import gsw

from importlib.resources import files as import_files

from mopdb.utils import read_yaml, MopException
from mopper.calc_utils import get_coords

# Global Variables
#----------------------------------------------------------------------

ice_density = 900 #kg/m3
snow_density = 300 #kg/m3

rd = 287.1
cp = 1003.5
p_0 = 100000.0
g_0 = 9.8067   # gravity constant
R_e = 6.378E+06
#----------------------------------------------------------------------


@click.pass_context
def overturn_stream(ctx, varlist, sv=False):
    """Returns ocean overturning mass streamfunction. 

    Calculation is:
    sum over the longitudes and cumulative sum over depth for ty_trans var
    then sum these terms to get final values

    Parameters
    ----------
    ctx : click context
        Includes obj dict with 'cmor' settings, exp attributes
    varlist: list( DataArray )
        List of ocean overturning mass streamfunction variables (ty_trans vars)
        From 1-3 if gm and/or submeso are present
    sv: bool
        If True units are sverdrup and they are converted to kg/s
        (default is False)

    Returns
    -------
    stream: DataArray 
        The ocean overturning mass streamfunction in kg s-1

    :meta private:
    """
    var_log = logging.getLogger(ctx.obj['var_log'])
    londim = varlist[0].dims[3]
    depdim = varlist[0].dims[1]
    var_log.debug(f"Streamfunct lon, dep dims: {londim}, {depdim}")
    # work out which variables are in list
    var = {'ty': None, 'gm': None, 'subm': None}
    for v in varlist:
        if '_gm' in v.name:
            var['gm'] = v
        elif '_submeso' in v.name:
            var['subm'] = v
        else:
            var['ty'] = v
    # calculation
    ty_lon = var['ty'].sum(londim)
    stream = ty_lon.cumsum(depdim)
    if var['gm'] is not None:
        stream += var['gm'].sum(londim)
    if var['subm'] is not None:
        stream += var['subm'].sum(londim)
    stream = stream - ty_lon.sum(depdim)
    if sv is True:
        stream = stream * 10**9
    return stream


def ocean_floor(var):
    """Not sure.. 

    Parameters
    ----------
    var : Xarray dataset
        pot_temp variable

    Returns
    -------
    vout : Xarray dataset
        ocean floor temperature?

        :meta private:
    """
    lv = (~var.isnull()).sum(dim='st_ocean') - 1
    vout = var.take(lv, dim='st_ocean').squeeze()
    return vout


def calc_global_ave_ocean(var, rho_dzt, area_t):
    """Calculate global ocean mass transport.

    Parameters
    ----------
    var : Xarray dataset
        ocean variable
    rho_dzt : Xarray dataset
        density transport
    area_t : Xarray dataset
        area transport

    Returns
    -------
    vnew : Xarray dataset
        global ocean mass transport

    :meta private:
    """
    mass = rho_dzt * area_t
    #PP would be better to get the correct dimension from variable and use them
    # rather than try and except
    
    try:
        vnew = var.weighted(mass).mean(dim=('st_ocean', 'yt_ocean', 'xt_ocean'), skipna=True)
    except Exception as e:
        vnew = var.weighted(mass[:, 0, :, :]).mean(dim=('x', 'y'), skipna=True)
    
    return vnew


@click.pass_context
def calc_global_ave_ocean(ctx, var, rho_dzt):
    """Returns global average ocean temperature

    NB needs checking

    Parameters
    ----------
    ctx : click context
        Includes obj dict with 'cmor' settings, exp attributes
    var : xarray.DataArray
        Input variable
    rho_dzt: Xarray DataArray
        sea_water_mass_per_unit_area dimensions: (time, depth, lat, lon)

    Returns
    -------
    vnew : xarray.DataArray
        output 

    :meta private:
    """
    fname = f"{ctx.obj['ancils_path']}/{ctx.obj['grid_ocean']}"
    ds = xr.open_dataset(fname)
    area_t = ds['area_t'].reindex_like(rho_dzt, method='nearest')
    mass = rho_dzt * area_t
    try: 
        vnew = np.average(var, axis=(1,2,3), weights=mass)
    except Exception as e:
        vnew = np.average(var, axis=(1,2), weights=mass[:,0,:,:])

    return vnew


@click.pass_context
def calc_overt(ctx, varlist, sv=False):
    """Returns overturning mass streamfunction variable 

    Parameters
    ----------
    ctx : click context
        Includes obj dict with 'cmor' settings, exp attributes
    varlist: list( DataArray )
        List of ocean transport variables (ty_trans vars)
        From 1-3 if gm and/or submeso are present
    sv: bool
        If True units are sverdrup and they are converted to kg/s
        (default is False)

    Returns
    -------
    overt: DataArray
        overturning mass streamfunction (time, basin, depth, gridlat) variable 

    """
    var_log = logging.getLogger(ctx.obj['var_log'])
    var1 = varlist[0]
    vlat, vlon = var1.dims[2:]
    mask = get_basin_mask(vlat, vlon)
    mlat = mask.dims[0]
    mlon = mask.dims[1]
    if [mlat, mlon] != [vlat, vlon]:
        
    # if mask uses different lat/lon interp mask to var dimesnions
        #mask = mask.sel(mlat=vlat, mlon=vlon, method="nearest")
        mask = mask.sel(**{mlat:var1[vlat], mlon:var1[vlon]}, method="nearest")
    var_log.debug(f"Basin mask: {mask}")
    # first calculate for global ocean
    glb  = overturn_stream(varlist)
    # atlantic and arctic basin have mask values 2 and 4 #TODO double check this
    var_masked = [ v.where(mask.isin([2, 4]), 0) for v in varlist]
    atl = overturn_stream(var_masked)
    #Indian and Pacific basin are given by mask values 3 and 5 #TODO double check this
    var_masked = [ v.where(mask.isin([3, 5]), 0) for v in varlist]
    ind = overturn_stream(var_masked)
    # now add basin dimension to resulting array
    glb = glb.expand_dims(dim={'basin': ['global_ocean']}, axis=1)
    atl = atl.expand_dims(dim={'basin': ['atlantic_arctic_ocean']}, axis=1)
    ind = ind.expand_dims(dim={'basin': ['indian_pacific_ocean']}, axis=1)
    overt = xr.concat([atl, ind, glb], dim='basin', coords='minimal')
    if ctx.obj['variable_id'][:5] == 'msfty':
        overt = overt.rename({vlat: 'gridlat'})
    overt['basin'].attrs['units'] = ""
    return overt


@click.pass_context
def calc_zostoga(ctx, ptemp, dht):
    """Returns Global Average Thermosteric Sea Level Change 
    
    See https://github.com/ACCESS-Community-Hub/ACCESS-MOPPeR/issues/182
    for details. 
    NB. no one tested if this gives correct results yet!!!

    Parameters
    ----------
    ctx : click context
        Includes obj dict with 'cmor' settings, exp attributes
    ptemp: DataArray
        Potential temperature in degrees Celsius
    dht: DataArray
        Model level thickness 

    Returns
    -------
    zostoga: DataArray
        Global Average Thermosteric Sea Level Change (time) variable 

    """
    var_log = logging.getLogger(ctx.obj['var_log'])
    t, dep, la, lo = ptemp.dims
    # gsw p_from_z expect negative depths
    depth = -1*ptemp[dep]
    # get latitude from grid ancil file
    coords = ptemp.encoding['coordinates'].split()
    lat, dum1, dum2, dum3 = get_coords(coords)
    # rename latitude index dimensions so they are the same as output
    ptemp_lalo = [la, lo]
    if any(x not in ptemp_lalo for x in lat.dims):
        for i,d in enumerate(lat.dims):
            lat = lat.rename({d: ptemp_lalo[i]})
    areacello = get_areacello()
    # press is absolute pressure minus 10.1325 dbar
    press = gsw.conversions.p_from_z(depth, lat)
    # constant salinity 35.00
    cso35 = xr.full_like(ptemp, 35.00)
    # constant temperature 4.00
    ctemp4 = xr.full_like(ptemp, 4.00)
    # calculate density with potential T and at constant 4 deg T
    rho = gsw.density.rho(cso35, ptemp, press)
    rho4 = gsw.density.rho(cso35, ctemp4, press)
    tmp = ((1. - rho/rho4) * dht).sum(dim=dep, skipna=True)
    # rename reindex coordinates to avoid differences
    if any(x not in ptemp_lalo for x in areacello.dims):
        for i,d in enumerate(areacello.dims):
            areacello = areacello.rename({d: ptemp_lalo[i]})
    areacello = areacello.reindex_like(tmp.isel(time=0),
        method='nearest')
    zostoga = ((tmp * areacello).sum(dim=[la, lo], skipna=True) / 
        areacello.sum(dim=[la, lo], skipna=True))
    return zostoga


@click.pass_context
def get_areacello(ctx, area_t=None):
    """Returns areacello

    Parameters
    ----------
    ctx : click context
        Includes obj dict with 'cmor' settings, exp attributes
    area_t: DataArray
        area of t-cells (default None then is read from ancil file)

    Returns
    -------
    areacello: DataArray
        areacello variable

    """
    var_log = logging.getLogger(ctx.obj['var_log'])
    fname = f"{ctx.obj['ancils_path']}/{ctx.obj['grid_ocean']}"
    ds = xr.open_dataset(fname)
    if area_t is None:
        if 'area_t' in ds.variables:
            area_t = ds.area_t
            ht = ds.ht
        elif 'area_T' in ds.variables:
            area_t = ds.area_T
            ht = ds.ds_10_12_T
        else:
            var_log.error(f"Neither area_t or area_T in ancil {fname}")
            raise MopException(f"Cannot retrieve T cell area in {fname}")
    areacello = xr.where(ht.isnull(), 0, area_t)
    return areacello


@click.pass_context
def get_basin_mask(ctx, lat, lon):
    """Returns first level of basin mask from lsmask ancil file.

    Lat, lon are used to work out which mask to use tt, uu, ut, tu
        where t/u refer to t/c cell, for x/y axis
    For example ut stands for c-cell lon and t-cell lat

    Parameters
    ----------
    ctx : click context
        Includes obj dict with 'cmor' settings, exp attributes
    lat: str
        latitude coordinate name
    lon: str
        longitude coordinate name

    Returns
    -------
    basin_mask: DataArray
        basin_mask(lat,lon)

    :meta private:
    """
    var_log = logging.getLogger(ctx.obj['var_log'])
    coords = ['t', 't']
    if 'xu' in lon:
        coords[0] = 'u'
    elif 'yu' in lat:
        coords[1] = 'u'
    fname = f"{ctx.obj['ancils_path']}/{ctx.obj['mask_ocean']}"
    if os.path.isfile(fname):
        ds = xr.open_dataset(fname)
    else:
        var_log.error(f"Ocean mask file {fname} doesn't exists")
        raise MopException(f"Ocean mask file {fname} doesn't exists")
    # based on coords select mask
    mask = f"mask_{''.join(coords)}cell"
    basin_mask = ds[mask].isel(st_ocean=0).fillna(0)
    return basin_mask
