# Module reference

Moved verbatim from the README.

## What it sizes

| Module | Method | Output |
|---|---|---|
| `lng_design/precool.py` | Vapor-compression cycle (propane), CoolProp EOS | Evaporator temp, compressor power, refrigerant flow, COP |
| `lng_design/compressor.py` | Polytropic head/efficiency (GPSA Ch. 13) + frame matching | Per-stage head, power, discharge temp, matched standard frame |
| `lng_design/amine_absorber.py` | Souders-Brown flooding + Kremser equation | Column diameter, theoretical stages, packed height |
| `lng_design/mche.py` | Composite-curve / MITA pinch analysis + tech classification | Minimum approach, pinch location, UA/area, coil-wound vs. plate-fin |
| `lng_design/vessels.py` | Souders-Brown gas capacity + residence time | Vessel diameter (standard size), seam-to-seam height |
| `lng_design/exchangers.py` | LMTD/U-area sizing, TEMA shell matching | Required area, tube count estimate, standard shell OD |
| `lng_design/air_cooler.py` | GPSA Ch. 9 / API 661 fin-fan sizing | Bay count/size, air flow, fan power |
| `lng_design/water_system.py` | CTI cooling-tower water balance | Circulation rate, evaporation, blowdown, total makeup |
| `lng_design/loads.py` | Utility duty aggregation (HMB-stream-table style) | Plant-wide heating/cooling load by utility medium |
| `lng_design/equipment_catalog.py` | Standard-variant catalogs + matcher | Vessel/shell/bay/frame standard sizes for every module above |
| `lng_design/end_flash.py` | Isenthalpic 2-phase mixture flash (CoolProp) | Flash gas / LNG split, flash composition, flash temperature |
| `lng_design/refrigerant_makeup.py` | Charge + reserve, max-fill vessel sizing | Refrigerant storage vessel diameter, length, volume |
| `lng_design/berth.py` | Mass-balance storage + Erlang-C (M/M/c) queueing | Storage tank volume, berth utilization, expected ship wait time |
| `lng_design/air_supply.py` | ISA/GPSA instrument-air demand aggregation | Air demand, compressor capacity, receiver volume |
| `lng_design/nitrogen_system.py` | Vessel-volume-exchange purge + blanketing | Purge volume, N2 generator capacity, LN2 vaporizer duty |
| `lng_design/process_selection.py` | Literature-grounded cycle screening | C3MR vs. DMR vs. AP-X recommendation + rationale |
| `lng_design/mche_vendor_selection.py` | Literature-grounded vendor comparison | APCI vs. Linde structured comparison |
| `lng_design/molecular_sieve.py` | GPSA Ch. 20 adsorber sizing | Bed diameter/height, number of beds, regen heater duty |
| `lng_design/cascade_loops.py` | 3-loop cascade, real CoolProp mixture flashes | NG/LRC/PMR duties, compressor power, DMR-vs-C3 precool comparison |
| `lng_design/mche_tube_design.py` | Dittus-Boelter/Shah/falling-film local HTCs, RATING (not sizing) | Achievable NG rundown for a fixed tube bundle, area/MITA-limited |
| `lng_design/liquefaction.py` | **Entry point.** Chains inlet separator, amine, sieve, trim cooler, C3 precool, LRC/MCHE pinch, end-flash, storage, refrigerant storage - and optional NGL fractionation + make-up MR - on one basis | `LiquefactionDesign`: every vessel/exchanger/loop result, total compression power, disclosed scope notes |
| `lng_design/regasification.py` | **Entry point.** Chains tank BOG, BOG compressors, send-out pumps/ORV/SCV, recondenser at full and turndown send-out, HP BOG route | `RegasificationDesign`: BOG by mode, machine counts and power, vaporizer duty, recondenser limits, decision notes |
| `lng_design/lpg_terminal.py` | **Entry point.** Fully-refrigerated LPG import: storage mass balance, tank BOG, compress-condense-return re-liquefaction (flash penalty, optional sub-cooling), berth queueing, liquid send-out pump + heater | `LPGTerminalDesign`: tanks, BOG by source, flash fraction / recycle factor, compressor power, heater duty, disclosed notes |
| `lng_design/regas_terminal.py` | CoolProp pump/vaporizer duties, ORV seawater balance, SCV fuel, BOG recondenser enthalpy balance | LP/HP pump power, vaporizer duty, seawater flow, unit counts, fuel gas, LNG/BOG ratio |
| `lng_design/tank_bog.py` | Tank geometry, layered-insulation heat ingress, equilibrium-vapor latent heat, unloading displacement + flash, barometric flash | Tank D/H/areas, BOG by source and mode (t/h), BOR %/day, nitrogen-rich BOG composition |
| `lng_design/bog_compressor.py` | Polytropic head on the real cryogenic BOG, stage count from max ratio, redundancy, turndown check | Stages, shaft power per machine, discharge T, frame/machine type, turndown fraction |
| `lng_design/fractionation.py` | Fenske-Underwood-Gilliland (Molokanov) + Kirkbride + O'Connell with CoolProp K-values, Souders-Brown hydraulics | Min/actual stages, reflux, feed tray, diameter, height, condenser/reboiler duty, condenser service |
| `lng_design/refrigerant_supply.py` | **Entry point.** Refrigerant demand by component, bullet storage at 2.5-3x demand (ethane stored cold - it is supercritical at ambient), and an ethane/propane/butane fractionation train scaled to fill it | `RefrigerantSupplyDesign`: storage per component, feed scale, product coverage and fill time vs spec |
| `lng_design/refrigerant_generation.py` | Spec checks, non-negative least-squares MR blending, make-up rate | Pass/fail per spec, source flows per kmol MR, make-up kmol/h |
| `lng_design/flowsheet.py` | Graphviz PFD + HMB-style stream table | Interactive process flow diagram tying every module together |
| `lng_design/optimize.py` | NSGA-II (via [pymoo](https://pymoo.org/)) | Pareto front for any of the above (e.g. power vs. exergy) |
