from dash import Dash, dcc, html, dash_table
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

import pandas as pd
from sqlalchemy import create_engine
from updater import update_prices 
import os
import sqlite3
import plotly.express as px
import dash 
engine = create_engine("sqlite:///portfolio.db")

if not os.path.exists("portfolio.db"):
    import data_base  # Initialize the database if it doesn't exist




app = Dash(__name__,use_pages=True)

app.layout = html.Div(
    [dash.page_container])
    

   
if __name__ == "__main__":
    app.run(debug=True)
