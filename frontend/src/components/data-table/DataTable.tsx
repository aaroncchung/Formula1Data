import clsx from "clsx";

type Column<T> = {
  key: string;
  header: string;
  align?: "left" | "right" | "center";
  render: (row: T) => React.ReactNode;
};

type DataTableProps<T> = {
  columns: Array<Column<T>>;
  rows: T[];
  emptyText?: string;
};

export function DataTable<T>({ columns, rows, emptyText = "No rows available." }: DataTableProps<T>) {
  return (
    <div className="overflow-x-auto rounded border border-line bg-panel">
      <table className="min-w-full text-sm">
        <thead className="bg-white/[0.03] text-xs uppercase tracking-[0.12em] text-slate-500">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className={clsx("px-4 py-3 font-semibold", {
                  "text-left": !column.align || column.align === "left",
                  "text-right": column.align === "right",
                  "text-center": column.align === "center"
                })}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="px-4 py-8 text-center text-slate-500" colSpan={columns.length}>
                {emptyText}
              </td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr key={index} className="border-t border-line/70 text-slate-200">
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={clsx("px-4 py-3", {
                      "text-left": !column.align || column.align === "left",
                      "text-right": column.align === "right",
                      "text-center": column.align === "center"
                    })}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

