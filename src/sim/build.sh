#!/bin/bash
# usage: build.sh N VARIANT [TAG]    (image 120x120; RTL = ../rtl; outputs obj_<VARIANT><TAG>_N<N>)
#   VARIANT: plane (orbit plane, EXT from env LBE_EXT, ORB_MID from env, default 3) | trivium | chacha | none
set -e
N=$1; V=$2; TAG=${3:-}
W=120; H=120
D=$(cd "$(dirname "$0")" && pwd); R=$D/../rtl
COMMON="-GN=$N -GIMG_W=$W -GIMG_H=$H -GFAST_CORE=1 -GPM_BYPASS=1 -GUSE_PPU=2 -GPART_ALIGN=1 -GRAM_WORDS=2048 -GFIFO_DEPTH=4"
case $V in
  plane)   G="-GUSE_KS=1 -GKS_IMPL=5 -GKS_GEOM=0 -GLBE_T=64 -GLBE_LEAN=6 -GLBE_PERT=${LBE_PERT:-8} -GPLANE_REG=1 -GORB_REG=1 -GORB_MID=${ORB_MID:-3} -GLBE_EXT=${LBE_EXT:-0}";;
  trivium) G="-GUSE_KS=1 -GKS_IMPL=6 -GKS_GEOM=0";;
  chacha)  G="-GUSE_KS=1 -GKS_IMPL=3 -GKS_GEOM=1 -GKS_ROUNDS=20 -GKS_QR=4";;
  none)    G="-GUSE_KS=0";;
  *) echo "unknown variant $V"; exit 1;;
esac
OUT=$D/obj_${V}${TAG}_N${N}
SRC="mpriscv tile router pixel_memory msg_fifo ppu ppu_stream ks_unit ks_unit2 ks_host chacha_core chacha_core2 lbe_unit lbe_dist trivium_core trivium_unit grain_core grain_unit picorv32"
FILES=""; for s in $SRC; do FILES="$FILES $R/$s.v"; done
${VERILATOR:-verilator} --cc --exe --build -O3 -j ${JOBS:-2} -MAKEFLAGS "OPT_FAST=${OPT_FAST:--O1}" --x-assign fast --x-initial fast +define+PROFILE \
  -Wno-fatal -Wno-WIDTH -Wno-PINMISSING -Wno-UNUSED -Wno-DECLFILENAME -Wno-CASEINCOMPLETE \
  -Wno-UNOPTFLAT -Wno-TIMESCALEMOD -Wno-UNSIGNED -Wno-PINCONNECTEMPTY -Wno-MULTIDRIVEN \
  -I$R --top-module mpriscv $COMMON $G -Mdir $OUT $FILES $D/tb.cpp -o Vmpriscv > $OUT.log 2>&1 || { tail -30 $OUT.log; exit 1; }
echo built $OUT/Vmpriscv
