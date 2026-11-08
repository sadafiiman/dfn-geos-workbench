# GEOS inputFiles validation matrix

Decks run: **78** · fail: **13** · pass: **62** · timeout: **3** · wall time: 60 min

| Category | pass | fail | timeout | xml-error | missing-file |
|---|---|---|---|---|---|
| compositionalMultiphaseFlow | 1 | 0 | 1 | 0 | 0 |
| compositionalMultiphaseWell | 1 | 2 | 0 | 0 | 0 |
| efemFractureMechanics | 8 | 0 | 1 | 0 | 0 |
| hydraulicFracturing | 2 | 0 | 0 | 0 | 0 |
| lagrangianContactMechanics | 1 | 5 | 0 | 0 | 0 |
| multiphaseFlowFractures | 4 | 0 | 0 | 0 | 0 |
| phaseField | 2 | 1 | 0 | 0 | 0 |
| poromechanics | 6 | 0 | 0 | 0 | 0 |
| poromechanicsFractures | 15 | 2 | 1 | 0 | 0 |
| simplePDE | 1 | 0 | 0 | 0 | 0 |
| singlePhaseFlow | 7 | 1 | 0 | 0 | 0 |
| singlePhaseFlowFractures | 8 | 0 | 0 | 0 | 0 |
| solidMechanics | 1 | 0 | 0 | 0 | 0 |
| surfaceGeneration | 5 | 0 | 0 | 0 | 0 |
| thermalSinglePhaseFlowFractures | 0 | 2 | 0 | 0 | 0 |

## Failed / skipped decks

### `compositionalMultiphaseWell/dome_mesh_bench.xml` — fail (rc=1, 0.8s)

```
***** Message :
Rank has no cells after initial redistribution.
```

### `compositionalMultiphaseWell/dome_mesh_smoke.xml` — fail (rc=1, 0.8s)

```
***** Message :
Rank has no cells after initial redistribution.
```

### `lagrangianContactMechanics/PassingCrack_smoke.xml` — fail (rc=1, 0.8s)

```
***** Message from FieldSpecifications (PassingCrack_base.xml, l.47):
xconstraint/fieldName (PassingCrack_base.xml, l.67): there are no field named `totalDisplacement` under the region `nodeManager`.
Available fields in nodeManager are:
{ SIFNode, childIndex, degreeFromCrack, degreeFromCrackTip, ghostRank, localToGlobalMap, parentIndex, ruptureTime }
```

### `lagrangianContactMechanics/SingleFracCompression_benchmark.xml` — fail (rc=1, 1.3s)

```
***** Message from tractionCollection/fieldName (SingleFracCompression_base.xml, l.111):
tractionCollection/fieldName (SingleFracCompression_base.xml, l.111): Target not found !
No wrapper named 'traction' found.
The wrappers of faceElementSubRegion are: { localToGlobalMap, globalToLocalMap, isExternal, ghostRank, domainBoundaryIndicator, localMaxGlobalIndex, maxGlobalIndex, numNodesPerElement, numEdgesPerElement, numFacesPerElement, elementCenter, elementVolume, nodeList, edgeList, elementAperture, elementArea, normalVector, tangentVector1, tangentVector2, dNdX, detJ, faceList, edgesToFractureConnectors, fractureConnectorsToEdges, fractureConnectorsToElementIndex, elem2dToCollocatedNodesBuckets, fractureElementsToCellRegions, fractureElementsToCellSubRegions, fractureElementsToCellIndices, K_IC_00, K_IC_01, K_IC_02, K_IC_10, K_IC_11, K_IC_12, K_IC_20, K_IC_21, K_IC_22, ruptureTime, ruptureRate }
***** Additional contexts:
***** - /domain/MeshBodies/CubeHex/meshLevels/Level0/ElementRegions/elementRegionsGroup/Fracture(SingleFracCompression_base.xml,l.31)/elementSubRegions/faceElementSubRegion
```

### `lagrangianContactMechanics/SingleFracCompression_smoke.xml` — fail (rc=1, 0.8s)

```
***** Message from tractionCollection/fieldName (SingleFracCompression_base.xml, l.111):
tractionCollection/fieldName (SingleFracCompression_base.xml, l.111): Target not found !
No wrapper named 'traction' found.
The wrappers of faceElementSubRegion are: { localToGlobalMap, globalToLocalMap, isExternal, ghostRank, domainBoundaryIndicator, localMaxGlobalIndex, maxGlobalIndex, numNodesPerElement, numEdgesPerElement, numFacesPerElement, elementCenter, elementVolume, nodeList, edgeList, elementAperture, elementArea, normalVector, tangentVector1, tangentVector2, dNdX, detJ, faceList, edgesToFractureConnectors, fractureConnectorsToEdges, fractureConnectorsToElementIndex, elem2dToCollocatedNodesBuckets, fractureElementsToCellRegions, fractureElementsToCellSubRegions, fractureElementsToCellIndices, K_IC_00, K_IC_01, K_IC_02, K_IC_10, K_IC_11, K_IC_12, K_IC_20, K_IC_21, K_IC_22, ruptureTime, ruptureRate }
***** Additional contexts:
***** - /domain/MeshBodies/CubeHex/meshLevels/Level0/ElementRegions/elementRegionsGroup/Fracture(SingleFracCompression_base.xml,l.31)/elementSubRegions/faceElementSubRegion
```

### `lagrangianContactMechanics/UnstructuredCrack_benchmark.xml` — fail (rc=1, 1.3s)

```
***** Message from FieldSpecifications (UnstructuredCrack_base.xml, l.46):
xconstraint/fieldName (UnstructuredCrack_base.xml, l.66): there are no field named `totalDisplacement` under the region `nodeManager`.
Available fields in nodeManager are:
{ SIFNode, childIndex, degreeFromCrack, degreeFromCrackTip, ghostRank, localToGlobalMap, parentIndex, ruptureTime }
```

### `lagrangianContactMechanics/UnstructuredCrack_smoke.xml` — fail (rc=1, 0.8s)

```
***** Message from FieldSpecifications (UnstructuredCrack_base.xml, l.46):
xconstraint/fieldName (UnstructuredCrack_base.xml, l.66): there are no field named `totalDisplacement` under the region `nodeManager`.
Available fields in nodeManager are:
{ SIFNode, childIndex, degreeFromCrack, degreeFromCrackTip, ghostRank, localToGlobalMap, parentIndex, ruptureTime }
```

### `phaseField/PhaseFieldPoromechanics_Nucleation_Wellbore.xml` — fail (rc=1, 3.2s)

```
***** Message :
Nodeset 'xneg': unsupported type 'long long' (use UInt8/16/32/64)
```

### `poromechanicsFractures/Contact/AugmentedLagrangianMultipliers/curvedFrac_smoke.xml` — fail (rc=1, 1.3s)

```
***** Message :
The region attributes { 1, 10, 11, 12, 13, 14, 15, 2, 3, 4, 5, 6, 7, 8, 9 } has not been referenced in any CellElementRegion.
The following cell-blocks has not been referenced in any region: { 10_hexahedra, 11_hexahedra, 12_hexahedra, 13_hexahedra, 14_hexahedra, 15_hexahedra, 1_hexahedra, 2_hexahedra, 3_hexahedra, 4_hexahedra, 5_hexahedra, 6_hexahedra, 7_hexahedra, 8_hexahedra, 9_hexahedra }.
Please add it in an existing CellElementRegion (through the 'cellBlocks' attribute), or consider creating a new one to describe your model.
```

### `poromechanicsFractures/EDFM/PoroElastic_efem-edfm_pennyCrack_smoke.xml` — fail (rc=1, 0.8s)

```
***** Message from FieldSpecifications (PoroElastic_efem-edfm_pennyCrack_base.xml, l.103):
sourceTerm (PoroElastic_efem-edfm_pennyCrack_base.xml, l.172): this FieldSpecification targets (an) empty set(s).
Set 'source' does not capture anything in the mesh 
```

### `singlePhaseFlow/thermalCompressible_referenceConductivity.xml` — fail (rc=1, 0.9s)

```
***** Message :
Rank has no cells after initial redistribution.
```

### `thermalSinglePhaseFlowFractures/egsCollab_thermalFlow/egsCollab_thermalFlow_injection_coarse.xml` — fail (rc=1, 3.3s)

```
***** Message from FieldSpecifications (egsCollab_thermalFlow_injection_base.xml, l.62):
TU_massFlux (egsCollab_thermalFlow_injection_base.xml, l.125): this FieldSpecification targets (an) empty set(s).
Set 'TU_injector':
  - Does not capture: ElementRegions/fracture
  - Instead, captures: nodeManager, edgeManager, faceManager
```

### `thermalSinglePhaseFlowFractures/egsCollab_thermalFlow/egsCollab_thermalFlow_injection_fine.xml` — fail (rc=1, 14.2s)

```
***** Message from FieldSpecifications (egsCollab_thermalFlow_injection_base.xml, l.62):
TU_massFlux (egsCollab_thermalFlow_injection_base.xml, l.125): this FieldSpecification targets (an) empty set(s).
Set 'TU_injector':
  - Does not capture: ElementRegions/fracture
  - Instead, captures: nodeManager, edgeManager, faceManager
```

### `compositionalMultiphaseFlow/benchmarks/SPE11/b/spe11b_vti_source_00840x00120.xml` — timeout (rc=-1, 240.2s)

```
##  - Time        : -(443y, 20d, 07h32m44s) out of 999y, 122d, 17h49m12s (28% completed)          ## | ##                  -13981484900 s / 31536000000 s                                                ## | ##  - Delta Time  : 4y, 364d, 00h43m12s (157680000 s)                                             ## | ##  - Cycle       : 131                                                                           ## |   Attempt:  0, ConfigurationIter:  0, NewtonIter:  0 |         ( Rmass Rvol ) = ( 5.26e-06 6.38e-08 )        ( Renergy ) = ( 2.67e-04 )        ( R ) = ( 2.67e-04 )
```

### `efemFractureMechanics/SneddonRotated_benchmark2.xml` — timeout (rc=-1, 900.6s)

```
***** Message :
Direct solver used for large system ( > 100,000 DOFs ). This may lead to high memory consumption and long computation times. Consider using an iterative solver for better performance.
```

### `poromechanicsFractures/EDFM/PoroElastic_efem-edfm_pennyCrack_benchmark.xml` — timeout (rc=-1, 900.6s)

```
***** Message :
Direct solver used for large system ( > 100,000 DOFs ). This may lead to high memory consumption and long computation times. Consider using an iterative solver for better performance.
```
