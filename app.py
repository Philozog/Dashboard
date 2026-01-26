from dash import Dash, html
import dash
import os
from sqlalchemy import create_engine

engine = create_engine("sqlite:///portfolio.db")
def init_db():
if not os.path.exists("portfolio.db"):
    import data_base  # Initialize the database if it doesn't exist

init_db()


app = Dash(__name__,use_pages=True)

app.layout = html.Div(
    [dash.page_container])
    
server=app.server
   
if __name__ == "__main__":
    app.run(debug=True)
