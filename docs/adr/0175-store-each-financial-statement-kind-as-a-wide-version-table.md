# Store each financial statement kind as a wide version table

Income, balance-sheet, and cash-flow facts use separate wide Canonical version tables with one row per Source Financial Version and nullable columns from the pinned source contract. This preserves report boundaries and efficient projection without multiplying reports into long-form rows or materializing daily expansions.
