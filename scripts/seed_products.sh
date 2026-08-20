#!/bin/bash
set -euo pipefail

# Create a products collection and add 20 records via the CLI
semantic-db collection create products \
  --field title string --embed --required \
  --field description text --embed \
  --field category enum pumps,motors,valves,sensors --embed \
  --field year int --embed \
  --field price float PLN --embed \
  || echo "collection exists, adding records"

# Add 20 product records covering all enum values with deliberate quiet pumps
semantic-db record add products --set title="Hydraulic Pump HPQ-400" category=pumps year=2019 price=4200
semantic-db record add products --set title="Electric Motor EM-2200W" category=motors year=2020 price=3500
semantic-db record add products --set title="Ball Valve BV-3IN" category=valves year=2018 price=250
semantic-db record add products --set title="Pressure Sensor PS-0-10" category=sensors year=2021 price=150

semantic-db record add products --set title="Quiet Pump QP-500" category=pumps year=2022 price=5200 description="Low-noise pump for industrial use"
semantic-db record add products --set title="Rotary Motor RM-5500W" category=motors year=2019 price=6800
semantic-db record add products --set title="Check Valve CV-2IN" category=valves year=2020 price=180
semantic-db record add products --set title="Temperature Sensor TS-100" category=sensors year=2021 price=120

semantic-db record add products --set title="Submersible Pump SP-1000" category=pumps year=2021 price=2800
semantic-db record add products --set title="Stepper Motor SM-NEMA23" category=motors year=2022 price=200
semantic-db record add products --set title="Gate Valve GV-4IN" category=valves year=2019 price=420
semantic-db record add products --set title="Flow Sensor FS-0-100LPM" category=sensors year=2020 price=280

semantic-db record add products --set title="Centrifugal Pump CP-250GPM" category=pumps year=2020 price=3900
semantic-db record add products --set title="Servo Motor SV-20Nm" category=motors year=2021 price=450
semantic-db record add products --set title="Relief Valve RV-250PSI" category=valves year=2022 price=350
semantic-db record add products --set title="Humidity Sensor HS-0-100RH" category=sensors year=2022 price=95

semantic-db record add products --set title="Quiet Low-Noise Pump QLP-600" category=pumps year=2023 price=6500 description="Designed for quiet operation in noise-sensitive environments"
semantic-db record add products --set title="Brushless Motor BL-3000RPM" category=motors year=2023 price=380
semantic-db record add products --set title="Solenoid Valve SV-24DC" category=valves year=2023 price=220
semantic-db record add products --set title="Accelerometer ACC-3AXIS" category=sensors year=2023 price=310

echo "Seeded 20 products in the 'products' collection"
