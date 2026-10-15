#!/bin/bash
# usage: anime_timing_variants.sh <keys_dir(NNNN.png, step 2)> <f0> <f1> <out_prefix>
# Builds 24 fps timing variants from 12 fps keys: _twos (hold 2), _threes (nearest key on 3-grid, hold 3), _rife24 (RIFE x2), all luminance-deflickered.
set -e
K=$1; F0=$2; F1=$3; O=$4; T=$(mktemp -d)
RIFE=/Users/mac/Code_Start/ml-stable-diffusion/mlx-tools/rife-mlx-venv/bin/rife-mlx
W=/Users/mac/Code_Start/ml-stable-diffusion/models-hub/rife-4.25-mlx
DF="deflicker=size=5:mode=pm"
i=0; for f in $(seq $F0 $F1); do k=$(( F0 + ((f-F0)/2)*2 )); cp $K/$(printf %04d $k).png $T/t$(printf %04d $i).png; i=$((i+1)); done
i=0; for f in $(seq $F0 $F1); do g=$(( F0 + ((f-F0)/3)*3 )); k=$(( F0 + ((g-F0+1)/2)*2 )); [ $k -gt $F1 ] && k=$F1; cp $K/$(printf %04d $k).png $T/h$(printf %04d $i).png; i=$((i+1)); done
i=0; for f in $(seq $F0 2 $F1); do cp $K/$(printf %04d $f).png $T/k$(printf %04d $i).png; i=$((i+1)); done
ffmpeg -loglevel error -y -framerate 24 -i $T/t%04d.png -vf "$DF,format=yuv420p" -c:v libx264 -crf 16 ${O}_twos.mp4
ffmpeg -loglevel error -y -framerate 24 -i $T/h%04d.png -vf "$DF,format=yuv420p" -c:v libx264 -crf 16 ${O}_threes.mp4
ffmpeg -loglevel error -y -framerate 12 -i $T/k%04d.png -vf "$DF,format=yuv420p" -c:v libx264 -crf 12 $T/k12.mp4
$RIFE -i $T/k12.mp4 -o ${O}_rife24.mp4 --multi 2 --weights_dir $W
rm -rf $T; echo VARIANTS_OK
