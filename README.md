# ACCESS MOPPeR 

This is the ACCESS Model Output Post-Processor (MOPPeR).

This code is derived from the APP4 (https://doi.org/10.5281/zenodo.7703469), initially created by Peter Uhe for CMIP5, and further developed for CMIP6-era by Chloe Mackallah.  
CSIRO, O&A Aspendale.


---

The MOPPeR is a CMORisation tool designed to post-process [ACCESS](https://research.csiro.au/access/) model output. The original APP4 main use was to produce [ESGF](https://esgf-node.llnl.gov/)-compliant formats, primarily for publication to [CMIP6](https://www.wcrp-climate.org/wgcm-cmip/wgcm-cmip6). The code was originally built for CMIP5, and was further developed for CMIP6-era activities.  
It used [CMOR3](https://cmor.llnl.gov/) and files created with the [CMIP6 data request](https://github.com/cmip6dr/dreqPy) to generate CF-compliant files according to the [CMIP6 data standards](https://docs.google.com/document/d/1os9rZ11U0ajY7F8FWtgU4B49KcB59aFlBVGfLC4ahXs/edit).The APP4 also had a custom mode option to allow users to post-process output without strict adherence to the ESGF standards. MOPPeR was developed to extend the custom mode as much as it is allowed by the CMOR tool, it can be used to produce CMIP6 compliant data but other standards can also be defined.
MOPPeR started as an attempt to upgrade the APP4 to python3 and the latest CMOR3 version. Obsolete packages were removed and eventually new functionalities to allow a user to create more easily configurations files and mappings were introduced. 
CMOR historically used CMIP6 Controlled Vocabularies as a metadata constraints. This has an effect on how the data is written in the files, variables' names, directory structure structure and filenames, and global attributes. To make this approach more flexible we introduced a new tool that helps the users create their own CV and any related files, as tables to defined variab;les, grids and mappings between the modeloutput and the CMOR style data.

For use on NCI's [Gadi](https://opus.nci.org.au/display/Help/Gadi+User+Guide) system only. 
Designed for use on ACCESS model output that has been archived using the ACCESS Archiver tool.

### Toubleshooting
Many users cannot immediately load the necessary conda environment that APP4 uses ('cmip6-publication'). The NCI project *hh5* must be joined (https://my.nci.org.au/mancini/project/hh5), and the following file created in your home directory:

Filename: ***~/.condarc***  
Contents:

    auto_activate_base: false
    envs_dirs:
      - /g/data/hh5/public/apps/miniconda3/envs

## Custom Mode

MOPPeR uses CMOR to write the files and manage the metadata as the APP4 did, however, it allows the use of a custom Controlled Vocabulary.
It is important to understand what CMOR expects and how it uses these tables.  

***Control Vocabulary***

***CMOR Tables***

*** ***

***mop_setup.py***  
This is main control script for the APP4 in custom mode. Once all variables have been set, simply run the script with ./custom_app4.sh to create the necessary files (job script, variable maps, etc) and submit the task to the job queue.  
Here you define:  
- Details about the experiment you wish to process, including the location of the archived data (see https://git.nci.org.au/cm2704/ACCESS-Archiver) and version of ACCESS.
- Metadata intended for the final datasets, including experiment and MIP names, ensemble number and branch times, for both the present experiment, and its parent experiment (if applicable; 'no parent' can also be used by setting *parent* to false).
- The variable(s) to process and generate. These can be set either by declaring a MIP Table (e.g., Amon, SIday, etc.) and variable (CMIP6 names) in the wrapper, or by creating a file-based list of variables (*VAR_SUBSET_LIST*) to read in.  
The CMIP6 data request file to use for variable definitions is also defined here. A default file that contains all APP4-ready CMIP6 variables can also be selected.
- NCI job information, including the intended write location of CMORised data and job files, and declaring job details (compute project, job queue (hugemem is recommended), and cpu/memory usage).

The CMOR logs (*$OUTPUT_LOC/APP_job_files/cmor_logs*) are overwritten by CMOR everytime it generates a file, and so for CMOR-specific log information you must run each problematic variable at time (variable/table declared in *custom_app4.sh*).


## Production Mode

