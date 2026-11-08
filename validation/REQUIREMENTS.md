# Task-1 requirements coverage across GEOS `inputFiles`

Decks analysed: **78** — fail 13, pass 62, timeout 3

## Capability matrix

| Requirement | decks with it | passed | failed/other |
|---|---|---|---|
| A. External VTK mesh import | 45 | 34 | 11 |
| B. Explicit fracture region | 27 | 27 | 0 |
| C. Conformal face elements | 18 | 18 | 0 |
| D. Embedded (EDFM/EFEM) elements | 22 | 17 | 5 |
| E. Rock-matrix region | 33 | 31 | 2 |
| F. Fracture-matrix coupling | 27 | 27 | 0 |
| **All of A+C+E+F together** | 7 | 7 | 0 |

## Decks that exercise the decisive path (external mesh + conformal fracture + matrix coupling)

| deck | status | s | VTK | face | embedded | matrix |
|---|---|---|---|---|---|---|
| `poromechanicsFractures/Contact/AugmentedLagrangianMultipliers/ALM_inclinedFault_ESG_friction_cohesion_smoke.xml` | pass | 82 | yes | yes | – | yes |
| `poromechanicsFractures/Contact/AugmentedLagrangianMultipliers/ALM_inclinedFault_ESG_smoke.xml` | pass | 79 | yes | yes | – | yes |
| `poromechanicsFractures/Contact/AugmentedLagrangianMultipliers/ALM_inclinedFault_ISG_DruckerPrager_smoke.xml` | pass | 98 | yes | yes | – | yes |
| `poromechanicsFractures/Contact/AugmentedLagrangianMultipliers/ALM_inclinedFault_ISG_smoke.xml` | pass | 78 | yes | yes | – | yes |
| `poromechanicsFractures/Contact/AugmentedLagrangianMultipliers/ALM_inclinedFault_ISG_well_smoke.xml` | pass | 58 | yes | yes | – | yes |
| `singlePhaseFlowFractures/fractureFlow_conforming_2d_vtk_input.xml` | pass | 2 | yes | yes | – | yes |
| `surfaceGeneration/cube_8.xml` | pass | 1 | yes | yes | – | yes |

## Per-category coverage

| Category | decks | A extern | B fracture | C conformal | D embedded | F coupled | pass |
|---|---|---|---|---|---|---|---|
| compositionalMultiphaseFlow | 2 | 1 | 1 | 0 | 1 | 1 | 1 |
| compositionalMultiphaseWell | 3 | 3 | 0 | 0 | 0 | 0 | 1 |
| efemFractureMechanics | 9 | 0 | 0 | 0 | 9 | 0 | 8 |
| hydraulicFracturing | 2 | 0 | 2 | 2 | 0 | 2 | 2 |
| lagrangianContactMechanics | 6 | 6 | 0 | 0 | 0 | 0 | 1 |
| multiphaseFlowFractures | 4 | 0 | 4 | 0 | 4 | 4 | 4 |
| phaseField | 3 | 3 | 0 | 0 | 0 | 0 | 2 |
| poromechanics | 6 | 6 | 0 | 0 | 0 | 0 | 6 |
| poromechanicsFractures | 18 | 14 | 7 | 5 | 4 | 7 | 15 |
| simplePDE | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| singlePhaseFlow | 8 | 8 | 0 | 0 | 0 | 0 | 7 |
| singlePhaseFlowFractures | 8 | 1 | 8 | 6 | 2 | 8 | 8 |
| solidMechanics | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| surfaceGeneration | 5 | 1 | 5 | 5 | 0 | 5 | 5 |
| thermalSinglePhaseFlowFractures | 2 | 0 | 0 | 0 | 2 | 0 | 0 |