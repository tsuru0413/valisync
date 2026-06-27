# Requirements Document: valisync-gui-axes

## Introduction

This sub-spec defines the implementation of an advanced multi-Y axis system. The goal is to allow simultaneous visualization of signals with different magnitudes while providing tools to organize them into vertical regions within a single shared timeline.

## Requirements

### Requirement 1: Multi-Column Y-Axis Grid (R1)
**User Story:** As an analyst, I want to arrange many scales in a grid to optimize my view.
1. THE GUI_Application SHALL support at least two vertical columns for Y-axes to the left of the plot area.
2. EACH column SHALL support an independent number of Y-axis rows.

### Requirement 2: Vertical Focus Regions (R2)
**User Story:** As an analyst, I want to assign signals to specific vertical slots on my screen.
1. THE GUI_Application SHALL assign each Y-axis to a "Home Region," defined by a vertical start position (percentage) and a height (percentage).
2. THE GUI_Application SHALL provide draggable dividers between Y-axis rows to adjust these percentages in real-time.

### Requirement 3: Auto-Fit Scaling (R3)
**User Story:** As an analyst, I want the waveforms to automatically expand when I give their axis more space.
1. THE GUI_Application SHALL automatically calculate the vertical scale of a signal such that its Y-range (0-100%) maps to the physical height of its Home Region.
2. WHEN a region is resized via a divider, THE associated waveforms SHALL stretch or compress vertically in real-time.

### Requirement 4: Unclipped Global Overlay (R4)
**User Story:** As an analyst, I want to see the peaks of my signals even if they exceed their assigned home area.
1. THE GUI_Application SHALL render waveforms across the entire plot area without vertical clipping.
2. IF a signal's value exceeds the range shown on its Y-axis, it SHALL continue drawing into the neighboring regions.

### Requirement 5: Context-Aware Drag and Drop (R5)
**User Story:** As an analyst, I want to decide where a signal goes based on where I drop it.
1. WHEN a signal is dropped onto an existing Y-axis scale, IT SHALL **replace (overwrite)** that axis's signal assignment with the dropped signal. WHEN dropped with **Ctrl held**, IT SHALL **add/join** the signal to that axis instead of replacing.
2. WHEN a signal is dropped onto the main plot area (background), THE GUI_Application SHALL create a new Y-axis and assign the signal to it. The new axis SHALL be appended at the bottom of the **inner column** (`column_count−1`) — **Rule A: fill-inner-first**.

### Requirement 6: Stable Layout on Deletion (R6)
**User Story:** As an analyst, I don't want my signals jumping around when I remove a secondary channel.
1. WHEN a signal or axis is removed, THE remaining Y-axis regions SHALL maintain their absolute positions and height ratios.
2. THE vacant space left by a deleted axis SHALL be treated as an "Empty Slot" that can be reclaimed by resizing adjacent axes.
