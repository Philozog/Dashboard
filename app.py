from dash import Dash, html
import dash
import os
from sqlalchemy import create_engine

base_dir=os.path.dirname(__file__)
db_path=os.path.join(base_dir,"portfolio.db")

engine = create_engine(f"sqlite:///{db_path}")


app = Dash(__name__,use_pages=True)

app.layout = html.Div(
    [dash.page_container])
    
server=app.server
   

