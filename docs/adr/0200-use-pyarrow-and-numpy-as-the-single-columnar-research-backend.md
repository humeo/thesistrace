# Use PyArrow and NumPy as the single columnar Research backend

The single Research executor uses PyArrow for bounded Parquet and columnar data flow and NumPy for explicit vectorized kernels, preserving deterministic ordering, missingness, and numeric contracts. It retains no row-materialized full-period path, alternate Polars or SQL engine, or versioned backend dispatcher.
