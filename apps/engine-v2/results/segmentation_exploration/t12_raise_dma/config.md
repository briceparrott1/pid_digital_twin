# t12_raise_dma  (leaves=12)

## Stop config
- min_dim: 800
- min_area: 1,000,000
- min_ink_density: 0.01
- dense_density_threshold: 0.03
- dense_min_dim: 400
- dense_min_area: 1,000,000

## Leaf segments
- root.L: 1787x3300  density=0.0100  stopped_by=density
- root.R.T.T: 3313x597  density=0.0158  stopped_by=size
- root.R.T.B: 3313x612  density=0.0119  stopped_by=size
- root.R.B.T.L.L.T: 840x782  density=0.0560  stopped_by=size
- root.R.B.T.L.L.B: 840x498  density=0.0231  stopped_by=size
- root.R.B.T.L.R.T: 984x580  density=0.0422  stopped_by=size
- root.R.B.T.L.R.B: 984x700  density=0.0357  stopped_by=size
- root.R.B.T.R.L: 745x1280  density=0.0089  stopped_by=density
- root.R.B.T.R.R: 744x1280  density=0.0199  stopped_by=size
- root.R.B.B.T: 3313x350  density=0.0173  stopped_by=size
- root.R.B.B.B.L: 1160x461  density=0.0104  stopped_by=size
- root.R.B.B.B.R: 2153x461  density=0.0988  stopped_by=size
