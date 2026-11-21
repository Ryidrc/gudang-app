"""XLSX export helper."""
from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from starlette.responses import Response


def export_xlsx(rows: list[dict], headers: list[str], filename: str) -> Response:
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"

    # Header styling
    header_fill = PatternFill(start_color="E4E6EB", end_color="E4E6EB", fill_type="solid")
    header_font = Font(bold=True)
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num, value=header)
        cell.font = header_font
        cell.fill = header_fill

    # Data rows
    for row_num, row_data in enumerate(rows, 2):
        for col_num, header in enumerate(headers, 1):
            val = row_data.get(header, "")
            # Handle datetime objects for Excel
            if isinstance(val, datetime):
                val = val.strftime("%Y-%m-%d %H:%M:%S")
            ws.cell(row=row_num, column=col_num, value=val)

    # Auto-adjust column widths
    for column in ws.columns:
        max_length = max(len(str(cell.value or "")) for cell in column)
        ws.column_dimensions[column[0].column_letter].width = max_length + 2

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
