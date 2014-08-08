from flask import Flask, abort, Response
import urllib
import urllib2
from bs4 import BeautifulSoup
import json, re, os
import cloudstorage as gcs
from google.appengine.api import urlfetch, files, app_identity

my_default_retry_params = gcs.RetryParams(initial_delay=0.2,
                                          max_delay=5.0,
                                          backoff_factor=2,
                                          max_retry_period=15)
gcs.set_default_retry_params(my_default_retry_params)

urlfetch.set_default_fetch_deadline(60)

app = Flask(__name__)
app.config['DEBUG'] = True

@app.route('/')
def hello():
    """Return a friendly HTTP greeting."""
    return 'Hello World!'

@app.route('/0/<domain>/<path:path>')
def wikipage(domain,path):
  if not domain.endswith('.wikipedia.org'):
    abort(404)

  bucket_name = os.environ.get('BUCKET_NAME', app_identity.get_default_gcs_bucket_name())
  bucket_name = 'attopedia'
  bucket = '/' + bucket_name

  cache_filename = bucket + '/0/' + domain + '/' + path

  try:
    gcs_file = gcs.open(cache_filename, 'r')
    data = gcs_file.read()
    return Response(data, mimetype='application/json')

  except Exception,e:
    print 'File not cached'
    title = path.replace('wiki/', '')
    title = urllib.unquote(title)
    title = title.replace('_', ' ')

    url = 'http://' + domain + '/' + path + '?action=render'

    result = urlfetch.fetch(url, deadline = 60)
    if result.status_code == 200:
      json = wiki_html_to_json_0(result.content, title)

      write_retry_params = gcs.RetryParams(backoff_factor=1.1)
      gcs_file = gcs.open(cache_filename,
                        'w',
                        content_type='application/json',
                        retry_params=write_retry_params)

      gcs_file.write(json)
      gcs_file.close()
      return Response(json, mimetype='application/json')
    else:
      abort(404)

@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, nothing at this URL.', 404

def http_get(url):
  return urllib2.urlopen(url).read()

def wiki_html_to_json_0(html, title = ''):
  soup = BeautifulSoup(html)

  sections = []
  current_section = { "title": title, 'subsections':[] }
  current_subsection = { "title": '', 'contentboxes':[] }

  # image for first slide -- get the first image from the article
  for img in soup.find_all('img'):
    if( ('width' in img.attrs and int(img.attrs['width']) > 64) or 
        ('height' in img.attrs and int(img.attrs['height']) > 64) ):
      url = img.attrs['src']
      if url.startswith('//'):
        url = 'http:' + url
      current_section['image_url'] = url
      break

  # title for first slide

  for e in soup.children:
    # new section
    if e.name == 'h2':
      if len(current_subsection['contentboxes'])>0:
        current_section['subsections'].append(current_subsection)

      if len(current_section['subsections'])>0:
        sections.append(current_section)

      current_section = { "title": e.string, 'subsections':[] }
      current_subsection = { "title": '', 'contentboxes':[] }

    # new subsection
    if e.name == 'h3':
      if len(current_subsection['contentboxes'])>0:
        current_section['subsections'].append(current_subsection)

      current_subsection = { "title": e.string, 'contentboxes':[] }

    # text paragraph
    if e.name == 'p':
      text = "".join(e.strings)
      text = re.sub(r'\[[0-9]+\]','', text).strip()
      if not text == "":
        current_subsection['contentboxes'].append( { "type":"text", "text": text } )

    # equation
    if e.name == 'dl':
      imgs = e.find_all('img')
      if(len(imgs)>0):
        url = imgs[0].attrs['src']
        if url.startswith('//'):
          url = 'http:' + url
        if 'image_url' not in current_section:
          current_section['image_url'] = url
        current_subsection['contentboxes'].append( { "type":"image", "url": url } )

    # captioned image
    if e.name == 'div' and 'class' in e.attrs and 'thumb' in e.attrs['class']:
      text = "".join(e.strings)
      imgs = e.find_all('img')
      if(len(imgs)>0):
        url = imgs[0].attrs['src']
        if url.startswith('//'):
          url = 'http:' + url
        caption = ''
        thumbcaptions = e.find_all(class_="thumbcaption")
        if(len(thumbcaptions)>0):
          caption = "".join(thumbcaptions[0].strings)
          caption = re.sub(r'\[[0-9]+\]','', caption).strip()
        current_subsection['contentboxes'].append( { "type":"image", "url": url, "caption": caption } )
        if 'image_url' not in current_section:
          current_section['image_url'] = url
  
  return json.dumps(sections)
