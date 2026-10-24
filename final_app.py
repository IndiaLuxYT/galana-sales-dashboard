import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from kenya_outline import DEPOTS, MAP_H, MAP_W, MIN_LON, PATH as KENYA_PATH, TOWNS, project

DB_PATH = Path(__file__).parent / "galana_sales_sample.db"

st.set_page_config(page_title="Galana Sales", page_icon="⛽", layout="centered")


@st.cache_data
def load_data() -> pd.DataFrame:
    # Read-only, so the demo can never change the database file.
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    df = pd.read_sql(
        """
        SELECT t.year_month, t.plant, p.plant_name, t.product_group,
               t.customer_type, t.billing_document, t.sold_to_party,
               t.billing_quantity, t.quantity_unit, t.net_amount, t.cost_amount,
               pr.material_name, c.customer_name
        FROM sales_transaction t
        JOIN plant p ON p.plant = t.plant
        JOIN product pr ON pr.material = t.material
        JOIN customer c ON c.customer_id = t.sold_to_party
        """,
        conn,
    )
    conn.close()
    return df


def chip_row(label: str, column: str, df: pd.DataFrame) -> str:
    """One row of single-select chips with an 'All' option. Returns the choice."""
    options = ["All"] + sorted(df[column].unique())
    choice = st.pills(label, options, default="All", key=column)
    return choice or "All"  # tapping the selected chip again clears it -> All


def apply_filter(df: pd.DataFrame, column: str, choice: str) -> pd.DataFrame:
    return df if choice == "All" else df[df[column] == choice]


df = load_data()

st.title("Galana Sales")
st.caption("Sample data, read from the local SQLite file. Works offline.")

depot = chip_row("Depot", "plant_name", df)
product = chip_row("Product", "product_group", df)
cust_type = chip_row("Customer type", "customer_type", df)

view = apply_filter(df, "plant_name", depot)
view = apply_filter(view, "product_group", product)
view = apply_filter(view, "customer_type", cust_type)

net_sales = view["net_amount"].sum()
invoices = view["billing_document"].nunique()
fuel_litres = view[view["quantity_unit"] == "L"]["billing_quantity"].sum()
customers = view["sold_to_party"].nunique()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Net sales (KES)", f"{net_sales / 1e6:,.1f}M")
c2.metric("Invoices", f"{invoices:,}")
c3.metric("Fuel litres", f"{fuel_litres / 1e6:,.2f}M")
c4.metric("Customers", f"{customers:,}")

st.subheader("Kenya depots")
st.caption("Bubble size = net sales. Ignores the depot chip so both depots stay visible; the chosen depot has a thick outline.")
map_view = apply_filter(apply_filter(df, "product_group", product), "customer_type", cust_type)
by_plant = (
    map_view.groupby("plant")
    .agg(net_amount=("net_amount", "sum"), customers=("sold_to_party", "nunique"))
    .reset_index()
)

def kenya_svg(rows: pd.DataFrame, chosen: str) -> str:
    """Kenya outline with one bubble per depot, drawn as plain SVG (no map tiles, works offline)."""
    biggest = max(rows["net_amount"].max(), 1) if not rows.empty else 1
    eq_y = project(0, MIN_LON)[1]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {MAP_W} {MAP_H}" width="{MAP_W}" height="{MAP_H}" font-family="Helvetica, Arial, sans-serif">',
        f'<path d="{KENYA_PATH}" fill="#8fb3a0" fill-opacity="0.25" stroke="#8fb3a0" stroke-width="3"/>',
        f'<line x1="0" x2="{MAP_W}" y1="{eq_y}" y2="{eq_y}" stroke="gray" stroke-width="1.5" stroke-dasharray="8 8" opacity="0.5"/>',
        f'<text x="{MAP_W - 6}" y="{eq_y - 8}" font-size="20" fill="gray" text-anchor="end" opacity="0.7">Equator</text>',
    ]
    for t in TOWNS:
        x, y = project(t["lat"], t["lon"])
        parts.append(f'<circle cx="{x}" cy="{y}" r="5" fill="gray" opacity="0.7"/>')
        parts.append(f'<text x="{x + 10}" y="{y + 7}" font-size="20" fill="gray">{t["name"]}</text>')
    for _, r in rows.iterrows():
        dep = DEPOTS[r["plant"]]
        x, y = project(dep["lat"], dep["lon"])
        radius = 22 + 40 * (r["net_amount"] / biggest) ** 0.5
        colour = "#0a6b6b" if r["plant"] == "NBO" else "#d9822b"
        width = 7 if chosen == dep["name"] + " Depot" else 3
        parts.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{colour}" fill-opacity="0.35" stroke="{colour}" stroke-width="{width}"/>')
        parts.append(f'<circle cx="{x}" cy="{y}" r="7" fill="{colour}"/>')
        # label on the side with room: left of the bubble in the east, right of it in the west
        east = x > MAP_W / 2
        lx = x - radius - 10 if east else x + radius + 10
        anchor = "end" if east else "start"
        parts.append(f'<text x="{lx}" y="{y - 4}" font-size="30" font-weight="bold" fill="#7d8c89" text-anchor="{anchor}">{dep["name"]}</text>')
        parts.append(f'<text x="{lx}" y="{y + 30}" font-size="26" fill="#7d8c89" text-anchor="{anchor}">KES {r["net_amount"] / 1e6:,.1f}M · {r["customers"]} cust.</text>')
    parts.append("</svg>")
    return "".join(parts)


st.image(kenya_svg(by_plant, depot), width=360)

st.subheader("Monthly net sales")
if view.empty:
    st.info("No sales match these filters.")
else:
    monthly = (
        view.groupby(["year_month", "plant_name"])["net_amount"]
        .sum()
        .unstack("plant_name", fill_value=0)
    )
    st.line_chart(monthly)

    st.subheader("Sales by product")
    by_product = view.groupby("material_name")["net_amount"].sum().sort_values()
    st.bar_chart(by_product, horizontal=True)

    st.subheader("Margin by product")
    st.caption("Profit as % of net sales. Costs are assumed sample values, not real Galana costs.")
    grouped = view.groupby("material_name")[["net_amount", "cost_amount"]].sum()
    margin = ((grouped["net_amount"] - grouped["cost_amount"]) / grouped["net_amount"] * 100).sort_values()
    st.bar_chart(margin, horizontal=True)

    left, right = st.columns(2)
    with left:
        st.subheader("B2B vs B2C")
        by_type = view.groupby("customer_type")["net_amount"].sum()
        st.bar_chart(by_type)
    with right:
        st.subheader("Profit")
        profit = net_sales - view["cost_amount"].sum()
        st.metric("Profit (sample cost, KES)", f"{profit / 1e6:,.1f}M")
        st.metric("Margin", f"{profit / net_sales * 100:.1f}%")

    st.subheader("Top customers")
    top = view.groupby("customer_name")["net_amount"].sum().nlargest(8).sort_values()
    st.bar_chart(top, horizontal=True)
