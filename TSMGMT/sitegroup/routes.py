import os
from flask import Blueprint, render_template, abort, send_from_directory, request, current_app
from flask_login import login_required
from ..db.connection import execute_query
from datetime import date, datetime, time
from .models import Sitegroup
from flask_login import login_required
from typing import List
from xml.dom import minidom, Node

sitegroup_bp = Blueprint('sitegroup', __name__, url_prefix='/sitegroup')

def pretty_xml(xml_string: str) -> str:
    try:
        doc = minidom.parseString(xml_string)

        # Recursively remove any TEXT_NODE that is pure whitespace
        def remove_blank_text_nodes(node):
            for child in list(node.childNodes):
                if child.nodeType == Node.TEXT_NODE and not child.data.strip():
                    node.removeChild(child)
                else:
                    remove_blank_text_nodes(child)

        remove_blank_text_nodes(doc)
        return doc.toprettyxml(indent="  ")
    except Exception:
        return xml_string

def normalize_xml_for_display(raw: str) -> str:
    # 1) Pretty-print
    pretty = pretty_xml(raw)
    lines = pretty.splitlines()

    # 2) Drop the XML declaration if present
    if lines and lines[0].strip().startswith('<?xml'):
        lines = lines[1:]

    # 3) Collapse multiple empty lines into one
    out, blank = [], False
    for ln in lines:
        if not ln.strip():
            if not blank:
                out.append('')
            blank = True
        else:
            out.append(ln)
            blank = False

    return "\n".join(out)

@login_required
@sitegroup_bp.route('/')
def index():
    # 1. Run the query
    sql = """
        SELECT
            directory,
            sitegroupid,
            systemname
        FROM sms.dbo.SiteGroupDataView
        WHERE ActiveStatus = 'Active'
        ORDER BY Directory
    """
    rows = execute_query(sql)
    # build a list of Sitegroup objects
    sitegroups: List[Sitegroup] = [
        Sitegroup(
            row["directory"],
            sitegroupid   = str(row["sitegroupid"]),
            systemname    = row["systemname"]
        )
        for row in rows
    ]
    return render_template('sitegroup/index.html', sitegroups=sitegroups)

@login_required
@sitegroup_bp.route('/sitegroup/<directory>')
def sitegroup_detail(directory):
    try:
        sg = Sitegroup(directory)
    except ValueError:
        abort(404)
    return render_template('sitegroup/detail.html', sg=sg)


@sitegroup_bp.route('/<directory>/contractcycle/<int:contractcycleid>')
def contractcycle_detail(directory, contractcycleid):
    # load the Sitegroup (and its cycles)
    sg = Sitegroup(directory)
    # find the one cycle
    cc = next((c for c in sg.contractcycle_list
               if c.contractcycleid == contractcycleid), None)

    if cc is None:
        abort(404)

    # now render a template, passing in both sg (if you need it) and cc
    return render_template('sitegroup/contractcycle_detail.html',
                           sg=sg,
                           cc=cc)

@login_required
@sitegroup_bp.route('/sitegroup/<directory>/file/<path:filename>')
def view_file(directory, filename):
    try:
        sg = Sitegroup(directory)
    except ValueError:
        abort(404)

    if filename not in sg.xml_files:
        abort(404)

    conf = sg.conf_path or ''
    file_path = os.path.join(conf, filename)
    if not file_path.startswith(os.path.abspath(conf)):
        abort(403)

    try:
        # Read as UTF-8 (replace bad chars), then normalize
        raw = open(file_path, 'r', encoding='utf-8', errors='replace').read()
        content = normalize_xml_for_display(raw)
    except Exception:
        abort(500)

    return render_template(
        'sitegroup/view_file.html',
        directory=directory,
        filename=filename,
        content=content
    )

@sitegroup_bp.route('/sitegroup/<directory>/file/<path:filename>/download')
@login_required
def download_file(directory, filename):
    """Let the user download the raw XML."""
    try:
        sg = Sitegroup(directory)
    except ValueError:
        abort(404)

    if filename not in sg.xml_files:
        abort(404)

    # send_from_directory will set correct headers
    return send_from_directory(
        directory=os.path.abspath(sg.conf_path),
        path=filename,
        as_attachment=True,
        download_name=filename,
        mimetype='application/xml'
    )
