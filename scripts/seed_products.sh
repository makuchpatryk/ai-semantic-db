#!/bin/bash
set -euo pipefail

# Seeds a 'products' collection with 20 records via the CLI.
# Override the entrypoint with SEMANTIC_DB_CLI if the package is installed on PATH.
CLI=${SEMANTIC_DB_CLI:-"uv run semantic-db"}

$CLI collection create products \
  --field "title:text:embed,required" \
  --field "description:text:embed" \
  --field "category:enum(pumps|motors|valves|sensors):embed" \
  --field "year:int:embed" \
  --field "price:float:embed:unit=PLN" \
  || echo "collection exists, adding records"

# add <title> <category> <year> <price> [description]
add() {
  local args=(--set "title=$1" --set "category=$2" --set "year=$3" --set "price=$4")
  if [ $# -ge 5 ]; then
    args+=(--set "description=$5")
  fi
  $CLI record add products "${args[@]}"
}

# 20 records covering every enum value, with deliberate quiet pumps for search to find
add "Hydraulic Pump HPQ-400" pumps 2019 4200
add "Electric Motor EM-2200W" motors 2020 3500
add "Ball Valve BV-3IN" valves 2018 250
add "Pressure Sensor PS-0-10" sensors 2021 150

add "Quiet Pump QP-500" pumps 2022 5200 "Low-noise pump for industrial use"
add "Rotary Motor RM-5500W" motors 2019 6800
add "Check Valve CV-2IN" valves 2020 180
add "Temperature Sensor TS-100" sensors 2021 120

add "Submersible Pump SP-1000" pumps 2021 2800
add "Stepper Motor SM-NEMA23" motors 2022 200
add "Gate Valve GV-4IN" valves 2019 420
add "Flow Sensor FS-0-100LPM" sensors 2020 280

add "Centrifugal Pump CP-250GPM" pumps 2020 3900
add "Servo Motor SV-20Nm" motors 2021 450
add "Relief Valve RV-250PSI" valves 2022 350
add "Humidity Sensor HS-0-100RH" sensors 2022 95

add "Quiet Low-Noise Pump QLP-600" pumps 2023 6500 "Designed for quiet operation in noise-sensitive environments"
add "Brushless Motor BL-3000RPM" motors 2023 380
add "Solenoid Valve SV-24DC" valves 2023 220
add "Accelerometer ACC-3AXIS" sensors 2023 310

echo "Seeded 20 products in the 'products' collection"
