import io
import re
from datetime import datetime, timedelta
from threading import Thread

import matplotlib

matplotlib.use('Agg')  # Usar el backend Agg antes de importar pyplot
import matplotlib.pyplot as plt
import mysql.connector
import pandas as pd
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from flask import (Flask, Response, redirect, render_template,
                   render_template_string, request, send_file, url_for)
from weasyprint import HTML

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

# Función para convertir fechas relativas a absolutas
def convertir_fecha_relativa(fecha_relativa):
    ahora = datetime.now()
    
    # Buscar la cantidad de tiempo y el tipo (horas, días, etc.)
    match = re.search(r'(\d+)\s*(hora|horas|día|días|minuto|minutos|semana|semanas)\s*atrás', fecha_relativa)
    
    if match:
        cantidad = int(match.group(1))
        unidad = match.group(2)
        
        if 'hora' in unidad:
            fecha = ahora - timedelta(hours=cantidad)
        elif 'día' in unidad:
            fecha = ahora - timedelta(days=cantidad)
        elif 'minuto' in unidad:
            fecha = ahora - timedelta(minutes=cantidad)
        elif 'semana' in unidad:
            fecha = ahora - timedelta(weeks=cantidad)
        else:
            return ahora  # Si no es un formato reconocido, retorna la fecha y hora actuales.
        
        return fecha.strftime('%Y-%m-%d %H:%M:%S')
    else:
        # Si no hay coincidencia, asumir que es la fecha actual
        return ahora.strftime('%Y-%m-%d %H:%M:%S')

# Función para verificar si una noticia ya existe en la base de datos
# Función para verificar si una noticia ya existe en la base de datos usando la URL
def noticia_existe(url):
    query = "SELECT COUNT(*) FROM noticias WHERE url = %s"
    cursor.execute(query, (url,))
    result = cursor.fetchone()
    return result[0] > 0


# Función para insertar o actualizar una noticia en la base de datos
def insert_noticia(title, date, content, image, url, source, full_content):
    # Obtener la fecha actual para el scraping
    fecha_scraping = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Verificamos si la noticia ya existe usando la URL como identificador único
    if noticia_existe(url):
        # Si la noticia existe, actualizamos los campos
        print(f"Noticia encontrada: {title}. Se actualizará.")
        query = """
        UPDATE noticias 
        SET title = %s, date = %s, content = %s, image = %s, source = %s, full_content = %s, fecha_scraping = %s
        WHERE url = %s
        """
        values = (title, date, content, image, source, full_content, fecha_scraping, url)
    else:
        # Si la noticia no existe, la insertamos
        print(f"Insertando noticia: {title}.")
        query = """
        INSERT INTO noticias (title, date, content, image, url, source, full_content, fecha_scraping) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (title, date, content, image, url, source, full_content, fecha_scraping)

    # Ejecutamos la consulta
    cursor.execute(query, values)
    db.commit()
    print(f"Operación completada para la noticia: {title}")

# Función para obtener el conteo de noticias scrapeadas por día usando la nueva columna 'fecha_scraping'
def get_noticias_por_dia():
    query = """
    SELECT DATE(fecha_scraping) as scrape_date, COUNT(*) as total_noticias 
    FROM noticias 
    GROUP BY scrape_date 
    ORDER BY scrape_date DESC
    """
    cursor.execute(query)
    result = cursor.fetchall()

    # Convertimos el resultado en un DataFrame de pandas para facilitar el manejo
    df = pd.DataFrame(result, columns=['scrape_date', 'total_noticias'])
    return df


# Función para obtener las noticias filtradas por una categoría
def get_noticias_por_categoria(categoria_nombre):
    query = "SELECT * FROM noticias WHERE source = %s ORDER BY date DESC"
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
        fecha_relativa = article.find('div', class_='post-date-bd').find('span').text.strip()
        date = convertir_fecha_relativa(fecha_relativa)  # Convertimos la fecha relativa a un formato estándar
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
    

@app.route('/descargar_pdf')
def descargar_pdf_rango():
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    categoria = request.args.get('categoria')

    # Construir la consulta SQL
    query = "SELECT * FROM noticias WHERE 1=1"
    params = []

    if fecha_inicio and fecha_fin:
        query += " AND date BETWEEN %s AND %s"
        params.extend([fecha_inicio, fecha_fin])

    if categoria:
        query += " AND source = %s"
        params.append(categoria)

    query += " ORDER BY date DESC"
    
    cursor.execute(query, params)
    noticias = cursor.fetchall()

    # Renderizamos un HTML con los datos de las noticias
    rendered_html = render_template('reporte_pdf.html', noticias=noticias, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, categoria=categoria)

    # Convertimos el HTML a PDF con WeasyPrint
    pdf = HTML(string=rendered_html).write_pdf()

    # Descargar el archivo PDF
    response = Response(pdf, mimetype="application/pdf")
    response.headers.set("Content-Disposition", "attachment", filename="reporte_noticias.pdf")
    return response



@app.route('/descargar_reporte_csv', methods=['GET'])
def descargar_reporte_csv():
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    categoria = request.args.get('categoria')

    # Construir la consulta SQL
    query = "SELECT * FROM noticias WHERE 1=1"
    params = []

    if fecha_inicio and fecha_fin:
        query += " AND date BETWEEN %s AND %s"
        params.extend([fecha_inicio, fecha_fin])

    if categoria:
        query += " AND source = %s"
        params.append(categoria)

    cursor.execute(query, params)
    noticias = cursor.fetchall()

    # Crear el CSV
    noticias_df = pd.DataFrame(noticias, columns=['ID', 'Título', 'Fecha', 'Contenido', 'Imagen', 'Fuente', 'Contenido Completo', 'Fecha de Scraping'])
    csv_data = noticias_df.to_csv(index=False)

    # Retornar el archivo CSV
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=reporte_noticias.csv'}
    )




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

    # Cargar todas las noticias desde la base de datos
    noticias = get_all_noticias()

    # Cargar las noticias del día presente
    noticias_del_dia = get_noticias_del_dia()

    # Obtener el número de noticias del día
    total_noticias_del_dia = len(noticias_del_dia)

    # Agregar el conteo de noticias a las categorías
    categorias_con_conteo = []
    for categoria in categorias:
        conteo = get_noticias_conteo_por_categoria(categoria['nombre'])
        categorias_con_conteo.append({
            'nombre': categoria['nombre'],
            'url': categoria['url'],
            'conteo': conteo
        })

    # Renderizar la plantilla con noticias, noticias del día, categorías, y conteo total de noticias
    total_noticias = len(noticias)
    return render_template('index.html', news=noticias, categorias=categorias_con_conteo, total_noticias=total_noticias, noticias_del_dia=noticias_del_dia, total_noticias_del_dia=total_noticias_del_dia)


# Función para obtener todas las noticias de la base de datos
def get_all_noticias():
    query = "SELECT * FROM noticias ORDER BY date DESC"
    cursor.execute(query)
    return cursor.fetchall()

def get_categorias():
    query = "SELECT DISTINCT source FROM noticias"
    cursor.execute(query)
    result = cursor.fetchall()
    return [categoria[0] for categoria in result]  # Retorna solo los nombres de las categorías



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
    # Obtener la noticia actual desde la base de datos
    cursor.execute("SELECT * FROM noticias WHERE id = %s", (noticia_id,))
    noticia = cursor.fetchone()
    
    if noticia:
        # La categoría o fuente de la noticia está en el campo noticia[5], asegúrate de que esto es correcto
        categoria = noticia[5]
        
        # Obtener las noticias relacionadas de la misma categoría (fuente), excluyendo la noticia actual
        query = "SELECT * FROM noticias WHERE source = %s AND id != %s ORDER BY date DESC LIMIT 5"
        cursor.execute(query, (categoria, noticia_id))  # Usamos placeholders para evitar problemas
        noticias_relacionadas = cursor.fetchall()

        # Imprimir para diagnóstico (puedes remover estos prints luego)
        print("Noticia actual:", noticia)
        print("Noticias relacionadas:", noticias_relacionadas)
        
        # Renderizamos el template con la noticia actual y las noticias relacionadas
        return render_template('detalle.html', noticia=noticia, noticias_relacionadas=noticias_relacionadas)
    else:
        return "No se encontró la noticia.", 404
    
@app.route('/graficos/noticias_por_dia')
def graficar_noticias_por_dia():
    # Obtener los datos de las noticias scrapeadas por día
    df = get_noticias_por_dia()

    # Crear un gráfico de barras con Matplotlib
    plt.figure(figsize=(10, 6))
    plt.bar(df['scrape_date'].astype(str), df['total_noticias'], color='blue')  # Usar solo la parte de la fecha
    plt.xlabel('Fecha de Scraping')
    plt.ylabel('Total de Noticias')
    plt.title('Noticias Scrapeadas por Día')
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Guardar la figura en un buffer de memoria
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    plt.close()

    # Devolver la imagen como una respuesta HTTP
    return Response(img.getvalue(), mimetype='image/png')

@app.route('/estadisticas')
def ver_estadisticas():
    return render_template('estadisticas.html')  # Cargar la página que mostrará las estadísticas

@app.route('/reportes', methods=['GET', 'POST'])
def ver_reportes():
    noticias = []
    categorias = get_categorias()  # Obtener las categorías de la base de datos
    if request.method == 'POST':
        # Obtener los valores del formulario
        fecha_inicio = request.form['fecha_inicio']
        fecha_fin = request.form['fecha_fin']
        categoria = request.form['categoria']

        # Construir la consulta SQL dinámicamente
        query = "SELECT * FROM noticias WHERE 1=1"
        params = []

        # Si se seleccionaron fechas, agregar a la consulta
        if fecha_inicio and fecha_fin:
            query += " AND date BETWEEN %s AND %s"
            params.extend([fecha_inicio, fecha_fin])

        # Si se seleccionó una categoría, agregar a la consulta
        if categoria:
            query += " AND source = %s"
            params.append(categoria)

        # Ejecutar la consulta
        query += " ORDER BY date DESC"
        cursor.execute(query, params)
        noticias = cursor.fetchall()

    return render_template('reportes.html', noticias=noticias, categorias=categorias)




@app.route('/admin', methods=['GET'])
def admin_page():
    # Obtener el número de página de la solicitud (por defecto la página 1)
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Mostrar 10 noticias por página

    # Obtener el término de búsqueda
    search_query = request.args.get('search', '')

    # Si hay una búsqueda, filtrar las noticias por el título
    if search_query:
        cursor.execute("SELECT * FROM noticias WHERE title LIKE %s LIMIT %s OFFSET %s", ('%' + search_query + '%', per_page, (page - 1) * per_page))
    else:
        cursor.execute("SELECT * FROM noticias LIMIT %s OFFSET %s", (per_page, (page - 1) * per_page))

    noticias = cursor.fetchall()

    # Obtener el número total de noticias
    if search_query:
        cursor.execute("SELECT COUNT(*) FROM noticias WHERE title LIKE %s", ('%' + search_query + '%',))
    else:
        cursor.execute("SELECT COUNT(*) FROM noticias")
    
    total_noticias = cursor.fetchone()[0]

    # Calcular el número total de páginas
    total_pages = (total_noticias // per_page) + (1 if total_noticias % per_page > 0 else 0)

    # Incluir los datos del gráfico de noticias por día
    df = get_noticias_por_dia()  # Llamar a la función que obtenga las noticias por día

    # Verificar si la solicitud es AJAX y retornar solo la tabla
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('tabla_noticias.html', noticias=noticias, page=page, total_pages=total_pages)

    # Si no es AJAX, renderizar la página completa
    return render_template('admin.html', noticias=noticias, page=page, total_pages=total_pages, search_query=search_query, noticias_por_dia=df)



@app.route('/admin/nueva', methods=['GET', 'POST'])
def nueva_noticia():
    if request.method == 'POST':
        title = request.form['title']
        date = request.form['date']
        content = request.form['content']
        image = request.form['image']
        url = request.form['url']
        source = request.form['source']
        full_content = request.form['full_content']

        # Insertar la nueva noticia
        insert_noticia(title, date, content, image, url, source, full_content)
        return redirect(url_for('admin_page'))

    return render_template('nueva_noticia.html')


@app.route('/admin/editar/<int:noticia_id>', methods=['GET', 'POST'])
def editar_noticia(noticia_id):
    # Obtener la noticia desde la base de datos
    cursor.execute("SELECT * FROM noticias WHERE id = %s", (noticia_id,))
    noticia = cursor.fetchone()

    if request.method == 'POST':
        title = request.form['title']
        date = request.form['date']  # La fecha ya debería estar en el formato 'YYYY-MM-DD' en el POST
        content = request.form['content']
        image = request.form['image']
        url = request.form['url']
        source = request.form['source']
        full_content = request.form['full_content']

        # Actualizar la noticia en la base de datos
        query = """
        UPDATE noticias SET title = %s, date = %s, content = %s, image = %s, url = %s, source = %s, full_content = %s 
        WHERE id = %s
        """
        cursor.execute(query, (title, date, content, image, url, source, full_content, noticia_id))
        db.commit()
        return redirect(url_for('admin_page'))

    # Convertir la tupla en lista para poder modificarla
    noticia = list(noticia)

    # Verificar si la fecha es una instancia de datetime y formatearla si es necesario
    if isinstance(noticia[2], datetime):
        noticia[2] = noticia[2].strftime('%Y-%m-%d')  # Convertir al formato YYYY-MM-DD para el campo <input type="date">
    else:
        # Si no es una fecha válida, dejamos el texto plano como "Hace 8 días" o como está en la base de datos
        noticia[2] = noticia[2]  # El texto plano se muestra tal como está

    return render_template('editar_noticia.html', noticia=noticia)



@app.route('/admin/eliminar/<int:noticia_id>')
def eliminar_noticia(noticia_id):
    cursor.execute("DELETE FROM noticias WHERE id = %s", (noticia_id,))
    db.commit()
    return redirect(url_for('admin_page'))

# Función que ejecutará el scraping periódicamente
def ejecutar_scraping_periodico():
    scrape_todas_las_categorias()
    print("Scraping periódico ejecutado.")

# Configurar el programador de tareas
scheduler = BackgroundScheduler()
scheduler.add_job(ejecutar_scraping_periodico, 'interval', minutes=5)
scheduler.start()

def get_noticias_del_dia():
    hoy = datetime.now().strftime('%Y-%m-%d')  # Fecha actual en formato 'YYYY-MM-DD'
    query = "SELECT * FROM noticias WHERE DATE(fecha_scraping) = %s ORDER BY fecha_scraping DESC"
    cursor.execute(query, (hoy,))
    return cursor.fetchall()


def get_noticias_por_dia():
    query = """
    SELECT DATE(fecha_scraping) as scrape_date, COUNT(*) as total_noticias 
    FROM noticias 
    GROUP BY scrape_date 
    ORDER BY scrape_date DESC
    """
    cursor.execute(query)
    result = cursor.fetchall()

    # Convertimos el resultado en un DataFrame de pandas para facilitar el manejo
    df = pd.DataFrame(result, columns=['scrape_date', 'total_noticias'])
    return df



# Obtener el conteo de noticias por categoría
def get_noticias_conteo_por_categoria(categoria_nombre):
    query = "SELECT COUNT(*) FROM noticias WHERE source = %s"
    cursor.execute(query, (categoria_nombre,))
    result = cursor.fetchone()
    return result[0]


# Iniciar scraping en un hilo separado
def start_scraping():
    print("Iniciando scraping en segundo plano...")
    scrape_todas_las_categorias()
    exportar_noticias_a_csv()
    print("Scraping completado.")
    
    

if __name__ == '__main__':
    # Iniciar el scraping en segundo plano después de que el servidor esté en marcha
    scraping_thread = Thread(target=start_scraping)
    scraping_thread.start()
    
    # Iniciar el servidor Flask
    app.run(debug=True)
