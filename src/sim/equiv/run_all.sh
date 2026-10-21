#!/bin/bash
# V3: shared versus private equivalence for N in 3 4 6 8 and EXT in 0..3 (iverilog from oss-cad-suite; simulation only)
set -e
cd "$(dirname "$0")"
IVERILOG=${IVERILOG:-iverilog}
VVP=${VVP:-vvp}
R=../../rtl
: > results.txt
failed=0
for N in 3 4 6 8; do
  for E in 0 1 2 3; do
    python3 ../../tools/plane_ref.py expected $N expected_N${N}_E${E}.mem keys.mem $E > /dev/null
    "$IVERILOG" -g2012 -I$R -s tb_equiv -P tb_equiv.N=$N -P tb_equiv.EXT=$E -o tb_N${N}_E${E}.vvp $R/lbe_dist.v $R/matched_tile.v $R/plane_mesh.v tb_equiv.v
    "$VVP" tb_N${N}_E${E}.vvp +EXPECTED=expected_N${N}_E${E}.mem > log_N${N}_E${E}.txt 2>&1 || { echo "FAIL N=$N EXT=$E" | tee -a results.txt; tail -5 log_N${N}_E${E}.txt; failed=1; continue; }
    grep -h "^PASS\|^CASE_PASS" log_N${N}_E${E}.txt | tee -a results.txt
  done
done

exit "$failed"
