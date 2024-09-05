from threading import Thread

import mysql.connector
import pandas as pd
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, send_file, url_for

# Conexión a la base de datos MySQL
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="noticias_db",
    port="3308",
)
cursor = db.cursor()

app = Flask(__name__)

# Función para verificar si una noticia ya existe en la base de datos
def noticia_existe(title, content):
    query = "SELECT COUNT(*) FROM noticias WHERE title = %s AND content = %s"
    cursor.execute(query, (title, content))
    result = cursor.fetchone()
    return result[0] > 0

# Función para eliminar duplicados en la tabla noticias
def eliminar_duplicados_noticias():
    query = """
    DELETE n1 FROM noticias n1
    INNER JOIN noticias n2 
    WHERE n1.id > n2.id AND n1.title = n2.title AND n1.content = n2.content
    """
    cursor.execute(query)
    db.commit()

# Función para insertar una noticia en la base de datos
def insert_noticia(title, date, content, image, url, source, full_content):
    # Primero verificamos si la noticia ya existe
    if noticia_existe(title, content):
        print(f"Noticia duplicada encontrada: {title}. No se insertará.")
    else:
        query = "INSERT INTO noticias (title, date, content, image, url, source, full_content) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        values = (title, date, content, image, url, source, full_content)
        cursor.execute(query, values)
        db.commit()
        print(f"Noticia insertada: {title}")

# Función para obtener todas las noticias de la base de datos
def get_all_noticias():
    cursor.execute("SELECT * FROM noticias")
    return cursor.fetchall()

# Función para obtener las noticias filtradas por una categoría
def get_noticias_por_categoria(categoria_nombre):
    query = "SELECT * FROM noticias WHERE source = %s"
    cursor.execute(query, (categoria_nombre,))
    return cursor.fetchall()

# Scraping del contenido detallado de Los Andes
def scrape_noticia_detallada_losandes(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Buscamos el contenido detallado dentro del bloque con la clase 'tdb-block-inner'
    full_content = soup.find('div', class_='tdb-block-inner').get_text(separator="\n").strip()
    
    return full_content

# Scraping del contenido detallado de Diario Sin Fronteras
def scrape_noticia_detallada_diariosinfronteras(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Buscamos el contenido detallado dentro del bloque con la clase 'post-content-bd'
    full_content = soup.find('div', class_='post-content-bd').get_text(separator="\n").strip()
    
    return full_content

# Scraping de Diario Sin Fronteras (Noticias) por categoría
def scrape_diariosinfronteras_por_categoria(categoria_url, categoria_nombre):
    response = requests.get(categoria_url)
    soup = BeautifulSoup(response.content, 'html.parser')

    articles = soup.find_all('div', class_='layout-wrap')
    for article in articles:
        title = article.find('h3', class_='entry-title').text.strip()
        date = article.find('div', class_='post-date-bd').find('span').text.strip()
        content = article.find('div', class_='post-excerpt').text.strip()
        image = article.find('img')['src']
        url = article.find('a')['href']

        # Scrape full content from Diario Sin Fronteras
        full_content = scrape_noticia_detallada_diariosinfronteras(url)
        
        # Insertar la noticia con el contenido detallado
        insert_noticia(title, date, content, image, url, categoria_nombre, full_content)

# Scraping de las categorías de Diario Sin Fronteras
def scrape_categorias_diariosinfronteras():
    url = "https://diariosinfronteras.com.pe/category/tacna/"
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    categorias = []

    # Busca el ul con el id 'menu-primary'
    menu = soup.find('ul', id='menu-primary')

    # Si encuentra el ul
    if menu:
        # Busca todos los elementos li dentro del ul
        for li in menu.find_all('li'):
            # Dentro del li, encuentra el enlace a
            a_tag = li.find('a')
            # Encuentra el span con la clase 'menu-label' que contiene el nombre de la categoría
            span_tag = a_tag.find('span', class_='menu-label') if a_tag else None
            
            if a_tag and span_tag:
                categoria = span_tag.text.strip()  # Extrae el texto del span (nombre de la categoría)
                url_categoria = a_tag['href']  # Extrae el href (URL de la categoría)
                categorias.append({'nombre': categoria, 'url': url_categoria})

    return categorias

# Scraping de todas las categorías y sus noticias
def scrape_todas_las_categorias():
    categorias = scrape_categorias_diariosinfronteras()
    
    # Iterar sobre cada categoría y extraer las noticias
    for categoria in categorias:
        categoria_url = categoria['url']
        categoria_nombre = categoria['nombre']
        scrape_diariosinfronteras_por_categoria(categoria_url, categoria_nombre)
        
        
def exportar_noticias_a_csv():
    query = "SELECT * FROM noticias"
    
    # Usar pandas para leer los datos de la base de datos
    noticias_df = pd.read_sql(query, db)

    # Exportar a CSV con codificación UTF-8 para mantener tildes y caracteres especiales
    noticias_df.to_csv('noticias_exportadas.csv', index=False, encoding='utf-8')

    print("Noticias exportadas correctamente a 'noticias_exportadas.csv' con pandas.")
    


# Ruta para descargar el CSV generado con noticias
@app.route('/descargar_csv')
def descargar_csv():
    exportar_noticias_a_csv()  # Llamar a la función para generar el CSV
    return send_file('noticias_exportadas.csv', as_attachment=True)

# Ruta principal de la aplicación para mostrar todas las noticias
@app.route('/')
def home():
    # Scraping de las categorías
    categorias = scrape_categorias_diariosinfronteras()

    # Cargar noticias desde la base de datos
    noticias = get_all_noticias()

    # Renderizar la plantilla con noticias y categorías
    return render_template('index.html', news=noticias, categorias=categorias)

# Ruta para mostrar noticias filtradas por categoría
@app.route('/categoria/<categoria_nombre>')
def noticias_por_categoria(categoria_nombre):
    # Cargar las noticias filtradas por la categoría seleccionada
    noticias = get_noticias_por_categoria(categoria_nombre)

    # También obtenemos todas las categorías para el menú
    categorias = scrape_categorias_diariosinfronteras()

    # Renderizar la plantilla index.html con las noticias filtradas y las categorías
    return render_template('index.html', news=noticias, categorias=categorias, categoria_seleccionada=categoria_nombre)

# Ruta para mostrar detalles de una noticia
@app.route('/noticia/<int:noticia_id>')
def noticia_detallada(noticia_id):
    cursor.execute("SELECT * FROM noticias WHERE id = %s", (noticia_id,))
    noticia = cursor.fetchone()
    
    if noticia:
        return render_template('detalle.html', noticia=noticia)
    else:
        return "No se encontró la noticia.", 404

# Iniciar scraping en un hilo separado
def start_scraping():
    print("Iniciando scraping en segundo plano...")
    scrape_todas_las_categorias()
    eliminar_duplicados_noticias()
    exportar_noticias_a_csv()
    print("Scraping completado.")

if __name__ == '__main__':
    # Iniciar el scraping en segundo plano después de que el servidor esté en marcha
    scraping_thread = Thread(target=start_scraping)
    scraping_thread.start()
    
    # Iniciar el servidor Flask
    app.run(debug=True)
