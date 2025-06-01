#!/bin/bash

# Use the first argument as FPS, default to 3 if not provided
FPS="${1:-3}"

# Prompt the user to click on the screen they want to record, showing the chosen FPS
read -p "Enter a description for the recording (enter for blank): " DESCRIPTION
echo "Click screen XXX to record at ${FPS} fps"
CLICK_INFO=$(xwininfo)

# Extract the absolute X/Y coordinates of the click
CLICK_X=$(echo "$CLICK_INFO" | awk '/Absolute upper-left X/ { print $4 }')
CLICK_Y=$(echo "$CLICK_INFO" | awk '/Absolute upper-left Y/ { print $4 }')

# Initialize variables
SEL_W=0
SEL_H=0
SEL_OX=0
SEL_OY=0

# Parse xrandr output to find which monitor contains the click
while read -r LINE; do
  if [[ $LINE =~ ([0-9]+)x([0-9]+)\+([0-9]+)\+([0-9]+) ]]; then
    W=${BASH_REMATCH[1]}
    H=${BASH_REMATCH[2]}
    OX=${BASH_REMATCH[3]}
    OY=${BASH_REMATCH[4]}

    # Check if the click falls within this monitor’s bounds
    if ((CLICK_X >= OX && CLICK_X < OX + W && CLICK_Y >= OY && CLICK_Y < OY + H)); then
      SEL_W=$W
      SEL_H=$H
      SEL_OX=$OX
      SEL_OY=$OY
      break
    fi
  fi
done < <(xrandr | grep " connected")

# If no monitor was matched, exit with an error
if ((SEL_W == 0)); then
  echo "Error: Could not determine monitor from click location." >&2
  exit 1
fi

# Compute output filename as ~/Videos/yymmdd_hhmmSS.mkv where SS is optional seconds
OUTPUT="$HOME/Videos/$(date +%y%m%d_%H%M).mkv"
if [ -f "$OUTPUT" ]; then
  echo "Warning: Output file $OUTPUT already exists. It will be overwritten."
  while true; do
    OUTPUT="$HOME/Videos/$(date +%y%m%d_%H%M%S).mkv"
    [ ! -f "$OUTPUT" ] && break
    sleep 1
  done
fi

# Derive a metadata filename by appending .meta.txt to the OUTPUT path
META="${OUTPUT}.meta.txt"

# Short-lived trap: if the script exits before the background loop starts,
# delete any partial META file to avoid leftover data.
trap 'rm -f "$META"' EXIT

[ "${DESCRIPTION// /}" == "" ] && echo "$DESCRIPTION" >"$META"

# Background loop: capture window titles on the selected screen every second
(
  while true; do
    # Get all window IDs from X11’s _NET_CLIENT_LIST
    WIN_IDS=$(xprop -root _NET_CLIENT_LIST |
      awk -F'# ' '{print $2}' |
      tr ',' ' ')

    for W in $WIN_IDS; do
      # Query geometry (X, Y, Width, Height) for window $W
      read -r X Y _Wd _Hd <<<"$(xwininfo -id "$W" |
        awk '
            /Absolute upper-left X/ { x=$4 }
            /Absolute upper-left Y/ { y=$4 }
            /Width:/               { w=$2 }
            /Height:/              { h=$2 }
            END { print x, y, w, h }
          ')"

      found_window=false
      # If the window’s top-left corner lies within the selected monitor:
      if ((X >= SEL_OX && X < SEL_OX + SEL_W && Y >= SEL_OY && Y < SEL_OY + SEL_H)); then
        found_window=true
        # Fetch the window’s title (WM_NAME)
        TITLE=$(xprop -id "$W" WM_NAME |
          awk -F '"' '{print $2}')
        echo "$TITLE" >>"$META"
      fi
    done

    if [[ $found_window == false ]]; then
      echo "<Blank>" >>"$META"
    fi

    sleep 1
  done
) &
BG_PID=$!

# Replace the short-lived trap with a final cleanup trap:
#   - kill the background loop
#   - dedupe the META file
trap 'kill "$BG_PID" 2>/dev/null
      if [[ -f "$META" ]]; then
        sort -u "$META" -o "$META"
      fi' EXIT

# Run ffmpeg with the detected geometry, using the specified FPS, no blur (YUV444p), and no audio
ffmpeg \
  -f x11grab \
  -framerate "${FPS}" \
  -video_size "${SEL_W}x${SEL_H}" \
  -i :0.0+"${SEL_OX},${SEL_OY}" \
  -c:v libx264 \
  -preset ultrafast \
  -crf 0 \
  -pix_fmt yuv444p \
  -an \
  "$OUTPUT"

# Run ffmpeg with the detected geometry, using the specified FPS, no blur (YUV444p), and no audio
#
# ffmpeg
#   -f x11grab                      # use X11 display capture as input
#   -framerate "${FPS}"             # capture at ${FPS} frames per second
#   -video_size "${SEL_W}x${SEL_H}" # set capture resolution to selected screen size
#   -i :0.0+"${SEL_OX},${SEL_OY}"   # grab from display :0.0 at the screen’s top-left offset
#   -c:v libx264                    # encode video using H.264 codec
#   -preset ultrafast               # use the ultrafast preset to minimize CPU usage
#   -crf 0                          # set CRF to 0 for lossless encoding in YUV domain
#   -pix_fmt yuv444p                # force full-resolution chroma (no 4:2:0 subsampling) to prevent color blur
#   -an                             # disable audio capture entirely
#   "$OUTPUT"                       # write output to ~/Videos/yymmdd_hhmm.mkv
