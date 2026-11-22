const inventory = [
  { item: "Coffee Beans (1 lb)", store: "Downtown", quantity: 42, reorderAt: 20 },
  { item: "Coffee Beans (1 lb)", store: "Uptown", quantity: 8, reorderAt: 20 },
  { item: "Paper Cups (100 pk)", store: "Downtown", quantity: 15, reorderAt: 10 },
  { item: "Paper Cups (100 pk)", store: "Airport", quantity: 4, reorderAt: 10 },
  { item: "Oat Milk (case)", store: "Uptown", quantity: 12, reorderAt: 6 },
  { item: "Oat Milk (case)", store: "Airport", quantity: 6, reorderAt: 6 },
  { item: "Croissants (dozen)", store: "Downtown", quantity: 3, reorderAt: 5 },
  { item: "Napkins (500 pk)", store: "Airport", quantity: 25, reorderAt: 8 },
];

const needsReorder = (row) => row.quantity <= row.reorderAt;

function renderInventory(rows) {
  const tbody = document.getElementById("inventory-body");
  tbody.replaceChildren(
    ...rows.map((row) => {
      const tr = document.createElement("tr");
      const flagged = needsReorder(row);
      if (flagged) tr.classList.add("reorder");

      const cells = [
        { text: row.item },
        { text: row.store },
        { text: String(row.quantity), className: "num" },
      ];
      for (const { text, className } of cells) {
        const td = document.createElement("td");
        td.textContent = text;
        if (className) td.className = className;
        tr.appendChild(td);
      }

      const flagCell = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = flagged ? "badge badge-reorder" : "badge badge-ok";
      badge.textContent = flagged ? "Reorder" : "OK";
      flagCell.appendChild(badge);
      tr.appendChild(flagCell);

      return tr;
    })
  );

  const flaggedCount = rows.filter(needsReorder).length;
  document.getElementById("summary").textContent =
    `${rows.length} items tracked, ${flaggedCount} need reordering.`;
}

renderInventory(inventory);
