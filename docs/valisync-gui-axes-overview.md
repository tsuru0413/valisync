# valisync-gui-axes — Overview

> Strategic overview for implementing advanced multi-Y axis layout in ValiSync.

## 1. Background
Professional time-series analysis requires comparing signals with vastly different units and scales (e.g., 5000 RPM vs 0.8V). A single shared Y-axis is insufficient. This sub-spec extends the GUI to support a flexible, high-density grid of Y-axes, allowing users to organize their workspace while maintaining a shared time context.

## 2. Key Requirements
| ID | Requirement | Description |
|---|---|---|
| R1 | Heterogeneous Grid | Support multiple columns of Y-axes, each with an independent number of rows. |
| R2 | Region-based Focus | Each Y-axis occupies a defined vertical "Home Region" (percentage of height). |
| R3 | Auto-Fit Scaling | Resizing a region's height automatically stretches/compresses the associated waveforms. |
| R4 | Unclipped Overlay | Waveforms are centered in their Home Region but are allowed to draw across the entire panel (no clipping). |
| R5 | Contextual D&D | Drop a signal on an axis to "join" it; drop on the plot area to create a new independent region. |
| R6 | Layout Persistence | Deleting a signal or axis does not rearrange other regions; the layout remains stable. |

## 3. Architecture
- **ViewModel**: `YAxisVM` manages range and height ratios. `GraphPanelVM` orchestrates a list of these axes.
- **View**: Utilizes nested `pyqtgraph.GraphicsLayout` for the grid. Overlays multiple `ViewBox`es with custom vertical coordinate transforms to achieve region-based mapping without clipping.

## 4. Success Criteria
- User can drag the divider between two Y-axes to change their height ratio.
- Waveforms update their vertical scale in real-time during dragging (Auto-Fit).
- Large signal spikes remain visible even if they exceed their Home Region's boundaries.
- Adding a signal to a new column creates a 2nd Y-axis column to the left of the plot.
