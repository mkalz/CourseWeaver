#!/usr/bin/env python
# -*- coding: utf-8 -*-
from lxml import etree
from sys import argv
import os,shutil
import unicodedata
import argparse
import zipfile
import requests



def getNombreFichero(nombre):
    nombre=elimina_tildes(nombre)
    nombre=elimina_caracteres_nombre_fichero(nombre)
    return nombre+".md"

def elimina_tildes(cadena):
    s = ''.join((c for c in unicodedata.normalize('NFD',unicode(cadena)) if unicodedata.category(c) != 'Mn'))
    return s

def elimina_caracteres_nombre_fichero(nomfich):
    car=("/","?","(",")"," ",",",".",":",";")
    
    nomfich=nomfich.replace("1.- ","")
    nomfich=nomfich.replace("2.- ","")
    nomfich=nomfich.replace("3.- ","")
    nomfich=nomfich.replace("4.- ","")
    
    for c in car:
        nomfich=nomfich.replace(c,"_")
    if nomfich[-1]=="_":
        nomfich=nomfich[:-1]
    nomfich=nomfich.replace("__","_")
    return nomfich

def crear_fichero(fich,dir):
    f=open(dir+fich,"w")
    f.close()

def escribir(dir,fich,texto="\n"):
    with open(dir+fich,"a") as fichero:
        fichero.write(texto.encode("utf-8"))
        if len(texto)>1 and texto[-1]!="\n":
            fichero.write("\n")

def images(html):
    html= html.replace("$@FILEPHP@$$@SLASH@$img$@SLASH@$","img/")
    html= html.replace("$@FILEPHP@$$@SLASH@$","../img/")
    return html


def copiar_imagenes(DIR_COPIA,DIR):
    filesdoc=etree.parse(DIR_COPIA+"/files.xml")
    imagenes=filesdoc.xpath("//file/filename[contains(text(),'.jpg') or contains(text(),'.png')  or contains(text(),'.gif') ]/..")
    for img in imagenes:
        shutil.copyfile(DIR_COPIA+"/files/%s/%s"%(img.find("contenthash").text[0:2],img.find("contenthash").text),DIR+"img/%s"%img.find("filename").text) 





def getSeccionesActividades(lista):

    doc = etree.parse('moodle_backup.xml')
    secciones=doc.find("information/contents/sections")
    for seccion in secciones:
        docseccion=etree.parse("%s/section.xml" % seccion.find("directory").text)
        
        sectionid=seccion.find("sectionid").text
        actividades=doc.xpath("//activity[sectionid=%s]"%sectionid)
        for actividad in actividades:
            
            tipo = actividad.find("modulename").text
            if tipo=="label":
            #    getLabel(actividad,DIR_COPIA,DIR,FICHERO)
                pass
            elif tipo=="url":
                getUrl(actividad,lista)
            elif tipo=="assign":
                getAssign(actividad,lista)
            elif tipo=="resource":
                getResource(actividad,lista)
            elif tipo=="page":
                getPage(actividad,lista)  
            
#def getLabel(actividad,DIR_COPIA,DIR,FICHERO):
#    doclabel=etree.parse(DIR_COPIA+"/%s/label.xml" % actividad.find("directory").text)
#    escribir(DIR,FICHERO)
#    escribir(DIR,FICHERO,"#### %s" % images(doclabel.find("label/intro").text))
#    escribir(DIR,FICHERO)
#
def getUrl(actividad,lista):
    docactivity=etree.parse("%s/url.xml" % actividad.find("directory").text)
    lista.append(["mod/url/view.php?id=%s"%actividad.find("moduleid").text,docactivity.find("url/externalurl").text])

def getAssign(actividad,lista):
    nomfich=getNombreFichero(actividad.find("title").text)
    lista.append(["mod/assign/view.php?id=%s"%actividad.find("moduleid").text,"doc/"+nomfich])

def getResource(actividad,lista):

    docresource=etree.parse("%s/resource.xml" % actividad.find("directory").text)
    fileid=docresource.getroot().get("contextid")
    docfiles=etree.parse("files.xml")
    fichero=docfiles.xpath("//file[contextid=%s]"%fileid)
    try:
        lista.append(["mod/resource/view.php?id=%s"%actividad.find("moduleid").text,"files/"+fichero[0].find("filename").text])
    except:
        pass

def getPage(actividad,lista):
    docpage=etree.parse("%s/page.xml" % actividad.find("directory").text)    
    nomfich=getNombreFichero(actividad.find("title").text)
    lista.append(["mod/page/view.php?id=%s"%actividad.find("moduleid").text,"doc/"+nomfich])
#    try:
#        escribir(DIR+"doc/",nomfich,"# %s" % actividad.find("title").text)
#        escribir(DIR+"doc/",nomfich,images(docpage.find("page/content").text))
#    except:
#        pass
#    escribir(DIR,FICHERO,"* [%s](%s)"%(actividad.find("title").text,"doc/"+nomfich))


def main():
    base="http://plataforma2.josedomingo.org/pledin/cursos/"
    base2="cloud2013/"
    lista=[]
    getSeccionesActividades(lista)
    bandera=False
    for l in lista:
        if ("files/" in l[1] or "doc/" in l[1]) and "url/" not in l[0]:
            r=requests.get(base+base2+l[1].replace(".md",".html"))
            if r.status_code==404:
                print r.url,r.status_code
                bandera=True
    if not bandera:
        for l in lista:
            print 'RewriteCond %%{QUERY_STRING} id=%s'%l[0].split("=")[1]
            if "url/" in l[0]:
                print 'RewriteRule ^%s$ %s'%(l[0].split("?")[0],l[1]+"? [R,L]")
            else:
                print 'RewriteRule ^%s$ %s'%(l[0].split("?")[0],base+base2+l[1].replace(".md",".html")+"? [R,L]")


if __name__ == '__main__':
    main()
    

        



