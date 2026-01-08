from dash import Dash, html
import dash
import os
engine = create_engine("sqlite:///portfolio.db")

if not os.path.exists("portfolio.db"):
    import data_base  # Initialize the database if it doesn't exist




app = Dash(__name__,use_pages=True)

app.layout = html.Div(
    [dash.page_container])
    

   
if __name__ == "__main__":
    app.run(debug=True)
