#!/bin/bash

loc_exp=(
025deg_jra55_iaf_omip2_cycle1
025deg_jra55_iaf_omip2_cycle2
025deg_jra55_iaf_omip2_cycle3
025deg_jra55_iaf_omip2_cycle4
025deg_jra55_iaf_omip2_cycle5
025deg_jra55_iaf_omip2_cycle6
1deg_jra55_iaf_omip2_cycle1
1deg_jra55_iaf_omip2_cycle2
1deg_jra55_iaf_omip2_cycle3
1deg_jra55_iaf_omip2_cycle4
1deg_jra55_iaf_omip2_cycle5
1deg_jra55_iaf_omip2_cycle6
1deg_jra55_iaf_omip2spunup_cycle34
1deg_jra55_iaf_omip2spunup_cycle35
1deg_jra55_iaf_omip2spunup_cycle36
1deg_jra55_iaf_omip2spunup_cycle37
1deg_jra55_iaf_omip2spunup_cycle38
1deg_jra55_iaf_omip2spunup_cycle39
)

for exp in ${loc_exp[@]}; do
  #./pre_qc4.sh $exp
  ./run_qc4.sh $exp
  #break
done
exit
