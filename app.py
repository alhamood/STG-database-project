# -*- coding: utf-8 -*-
"""
Created on Tue Dec  8 14:02:36 2015

STG Database Web Server

This python app runs a database server specifically designed for collecting data from
preparations of the stomatogastric ganglion (STG). It manages user accounts, allows
entry of experimental data for experiments containing many conditions, and allows file
uploads to be associated with experiments (for example of raw data). 

Detailed descriptions for users and administrators in the associated readme file.

Original code respository @ https://github.com/alhamood/STG-database-project

@author: Albert W. Hamood
"""

from flask import Flask, render_template, request, redirect, url_for, g, make_response, send_from_directory, session
from flask.ext.login import LoginManager, UserMixin, login_required
from wtforms import Form, validators, fields, widgets
from werkzeug import secure_filename
from shutil import rmtree
import os
import sys
import zipfile
import random
import string
import logging
import hashlib
import flask.ext.login
import simplejson as json
import pandas as pd

# Initialize application using the Flask module
app = Flask(__name__)
login_manager = LoginManager()
login_manager.init_app(app)

global extra_nerves_global
global intra_neurons_global
global experiment_flags_global

extra_nerves_global = ['lvn', 'pdn', 'pyn', 'lpn', 'mvn', 'dgn', 'lgn', 'aln',
            'stn', 'dvn', 'son', 'ion', 'dpon']

intra_neurons_global = ['PD', 'LP', 'PY', 'VD', 'IC', 'Int1', 'LG', 'DG', 'GM', 'MG',
            'H', 'AGR', 'AB', 'CoG', 'OeG', 'MCN1', 'MCN5']

experiment_flags_global = ['VoltageClamp', 'TempRamp', 'IsolatedNeurons', 'DynamicClamp',
              'Decentralization', 'Neuromodulation', 'Immuno', 'Published', 'LongTerm']


app.logger.addHandler(logging.StreamHandler(sys.stdout))
app.logger.setLevel(logging.ERROR)

# The following bits load in databases for users, metadata, and processed data
# as well as for basic web server configuration
with open('config.json') as json_data:
  config = json.load(json_data)
  json_data.close()


with open('databases/user_pdatabase.json') as json_data:
  user_pdatabase = json.load(json_data)
  json_data.close()


with open('databases/user_database.json') as json_data:
  user_database = json.load(json_data)
  json_data.close()
    
  
with open('databases/metadata.json') as json_data:
  metadata = json.load(json_data)
  json_data.close()
  
  
with open('databases/processed_data.json') as json_data:
  proc_data = json.load(json_data)
  json_data.close()

  
# Basic user class, required for Flask-Login which handles user sessions
class User(UserMixin):
  pass


# These classes handle forms that are passed to html templates using WTForms
class LoginForm(Form):
  username = fields.TextField('Username')
  password = fields.PasswordField('Password')


class EditUserForm(Form):
  email = fields.TextField('email', [
    validators.Email(message='Not an email address.')])
  surname = fields.TextField('Surname', [
    validators.Length(max=25, message='25 characters max'),
    validators.InputRequired(message='Surname required')])
  lab = fields.TextField('Lab PI surname', [
    validators.Length(max=20, message='20 characters max'),
    validators.InputRequired(message='Lab PI surname required')])


class UserForm(EditUserForm):
  username = fields.TextField('Username', [
    validators.Length(max=20, message='Maximum 20 characters'),
    validators.Regexp(r'^[\w_]+$', message='Alphanumeric characters only (underscore _ ok)'),
    validators.InputRequired(message='Username is required')])


class NewUserForm(UserForm):
  password = fields.PasswordField('Password', [
    validators.InputRequired(message='Password Field(s) Empty'),
    validators.EqualTo('confirm', message='Passwords unmatched.')])
  confirm = fields.PasswordField('Password')


class PasswordChangeForm(Form):
  oldpassword = fields.PasswordField('Old Password', [
    validators.InputRequired(message='Please enter old password')])
  password = fields.PasswordField('New Password', [
    validators.InputRequired(message='Password Field(s) Empty'),
    validators.EqualTo('confirm', message='Passwords unmatched.')])
  confirm = fields.PasswordField('New Password (reenter)')  


class DeleteForm(Form):
  verify = fields.TextField('Type DELETE to confirm.')


class AdminActionForm(Form):
  username = fields.TextField('Username')
  action = fields.SelectField('Action', choices = [
    ('edit', 'Edit User'), ('delete', 'Delete User'),
    ('password', 'Reset Password'), ('activate', 'Activate User Uploads'),
    ('deactivate', 'Deactivate User Uploads')])


class UploadActionForm(Form):
  identifier = fields.IntegerField('Experiment index (number in left column)', [
    validators.Optional()])
  action = fields.SelectField('Action', choices=[
    ('editP', 'Edit / Upload Data (conditions and files)'),
    ('editM', 'Edit Metadata'),   
    ('delete', 'Delete Experiment')])


class ExperimentActionForm(Form):
  identifier = fields.IntegerField('Condition index (number in left column)', [
    validators.Optional()])
  action = fields.SelectField('Action', choices=[
    ('edit', 'Edit Condition Data'),
    ('delete', 'Delete Condition')])


class FileDeleteForm(Form):
  identifier = fields.IntegerField('File index (number in left column)')
  confirm = fields.TextField(
    'Type DELETE here to delete file with index entered above. Cannot be undone!',
    [validators.Regexp('DELETE', message=('Did not type DELETE'))]) 


class NewConditionForm(Form):
  name = fields.TextField('Condition Name', [
    validators.length(min=2, max=20, message='2-20 characters'),
    validators.Regexp(r'^[\w_]+$', message='Alphanumeric characters only (underscore _ ok)'),
    validators.InputRequired(message='Must enter a condition name')])


class FileDownloadForm(Form):
  identifier = fields.IntegerField('Experiment index (number in left column)')


class ReadMeForm(Form):
  read_me = fields.TextAreaField('Please add to the read_me file to describe uploaded files')


class MetadataForm(Form):
  exp_date = fields.DateField('Experiment Date',  [
    validators.InputRequired(message='Experiment Date is Required')], format='%m/%d/%Y')
  animal_date = fields.DateField('Animal Arrival Date', [
    validators.Optional()], format='%m/%d/%Y')
  experimenter = fields.TextField('Experimenter Surname', [
    validators.Length(max=20, message='20 characters max')])
  lab = fields.TextField('Lab PI Surname', [
    validators.Length(max=20, message='20 characters max')])  
  temp = fields.IntegerField('Experiment Baseline Temperature in C', [validators.Optional()])
  tanktemp = fields.IntegerField('Animal Tank Temperature in C', [validators.Optional()])
  species = fields.TextField('Species', [
    validators.Length(max=20, message='20 characters max')])
  saline = fields.SelectField('Saline', choices = [
    ('cancer-std', 'Cancer standard'), ('homarus-std', 'Homarus standard'),
    ('pand-std', 'Pan. standard'), ('alt', 'Altered (describe, or provide ref. in notes)')])
  intra_sol = fields.SelectField('Intracellular solution', choices=[
    ('none', 'None'), ('KCl', 'KCl'), ('KAcetate', 'KAcetate'), ('K2SO4', 'K2SO4'),
    ('Hooper', 'Hooper et al solution'), ('alt', 'Altered (describe, or provide ref. in notes)')])
  notes = fields.TextAreaField('Purpose / Notes', [
    validators.length(max=1000, message='1000 characters max')])


class CheckboxesForm(Form):
  global extra_nerves_global
  global intra_nerves_global
  global experiment_flags_global
  nerves = fields.SelectMultipleField('Nerves ', choices = [(nerve, nerve) for nerve in extra_nerves_global], 
    option_widget=widgets.CheckboxInput(), widget=widgets.ListWidget(prefix_label=False))
  neurons = fields.SelectMultipleField('Neurons ', choices = [(neuron, neuron) for neuron in intra_neurons_global], 
    option_widget=widgets.CheckboxInput(), widget=widgets.ListWidget(prefix_label=False)) 
  flags = fields.SelectMultipleField('Experiment Flags ', choices = [(flag, flag) for flag in experiment_flags_global], 
    option_widget=widgets.CheckboxInput(), widget=widgets.ListWidget(prefix_label=False))                           


class NewMetadataForm(MetadataForm):
  exp_id = fields.TextField('Experiment ID (such as lab notebook and page)', [
    validators.Length(max=20, message='20 characters max'),
    validators.Regexp(r'^[\w_]+$', message='Alphanumeric characters only (underscore _ ok)'),
    validators.InputRequired(message='You must provide a unique ID')])


class ProcessedDataForm(Form):
  exp_temp = fields.IntegerField('Condition temperature in C', [validators.Optional()])
  pyl_hz = fields.DecimalField('Pyloric frequency (Hz)', [validators.Optional()], places=5)
  pyl_cycvar = fields.DecimalField('Pyloric cyc-to-cyc var (%)', [validators.Optional()], places=5)
  pyl_niqr = fields.DecimalField('Pyloric frequency NIQR', [validators.Optional()], places=5)
  gas_hz = fields.DecimalField('Gastric frequency (Hz)', [validators.Optional()], places=5)
  gas_cycvar = fields.DecimalField('Gastric cyc-to-cyc var (%)', [validators.Optional()], places=5)
  gas_niqr = fields.DecimalField('Gastric frequency NIQR', [validators.Optional()], places=5)
  pd_off = fields.DecimalField('PD off phase (duty cycle, 0-1)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5)
  pd_spikes = fields.DecimalField('PD spikes/burst', [validators.Optional()])
  lp_on = fields.DecimalField('LP on phase (0-1, from PD start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5) 
  lp_off = fields.DecimalField('LP off phase (0-1, from PD start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5)
  lp_spikes = fields.DecimalField('LP spikes/burst', [validators.Optional()])
  py_on = fields.DecimalField('PY on phase (0-1, from PD start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5) 
  py_off = fields.DecimalField('PY off phase (0-1, from PD start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5)
  py_spikes = fields.DecimalField('PY spikes/burst', [validators.Optional()]) 
  vd_on = fields.DecimalField('VD on phase (0-1, from PD start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5) 
  vd_off = fields.DecimalField('VD off phase (0-1, from PD start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5)
  vd_spikes = fields.DecimalField('VD spikes/burst', [validators.Optional()])
  lg_off = fields.DecimalField('Gastric LG off phase (duty cycle, 0-1', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5)
  lg_spikes = fields.DecimalField('Gastric LG spikes/burst', [validators.Optional()]) 
  dg_on = fields.DecimalField('Gastric DG on phase (0-1, from LG start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5) 
  dg_off = fields.DecimalField('Gastric DG off phase (0-1, from LG start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5)
  dg_spikes = fields.DecimalField('Gastric DG spikes/burst', [validators.Optional()])
  gm_on = fields.DecimalField('Gastric GM on phase (0-1, from LG start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5) 
  gm_off = fields.DecimalField('Gastric GM off phase (0-1, from LG start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5)
  gm_spikes = fields.DecimalField('Gastric GM spikes/burst', [validators.Optional()])
  mg_on = fields.DecimalField('Gastric MG on phase (0-1, from LG start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5) 
  mg_off = fields.DecimalField('Gastric MG off phase (0-1, from LG start)', [
    validators.NumberRange(min=0, max=1, message='range 0-1 (not radians)'),
    validators.Optional()], places=5)
  mg_spikes = fields.DecimalField('Gastric MG spikes/burst', [validators.Optional()])
  blank1 = fields.DecimalField('Blank Field 1 (describe in notes)', [validators.Optional()], places=5)
  blank2 = fields.DecimalField('Blank Field 2 (describe in notes)', [validators.Optional()], places=5)
  blank3 = fields.DecimalField('Blank Field 3 (describe in notes)', [validators.Optional()], places=5)


# Functions for making dataframes from databases to serve in html templates     
def MakeDF(data, column_names):
  df = pd.DataFrame(data.values(), columns = column_names)
  df.index = user_database.keys() 
  return df


def MakeMetaDF(data):
  column_names = ['User', 'Exp ID', 'Exp Date','Animal Date', 'Experimenter', 'Lab',
    'Temp (C)', 'Tank Temp (C)', 'Species', 'Saline', 'Intra Sol.', 'Conditions',
    'Files', 'Nerves', 'Neurons', 'Flags', 'Notes']
  df = pd.DataFrame(data.values(), columns = column_names, index=data.keys())
  df = df.sort_values(by='Exp Date')
  return df


def MakeCondDF(data):
  column_names = ['cond_name', 'temp', 'pyl_hz','pyl_cycvar','pyl_niqr','gas_hz','gas_cycvar',
    'gas_niqr','pd_off','pd_spikes','lp_on','lp_off','lp_spikes','py_on','py_off',
    'py_spikes','vd_on','vd_off','vd_spikes','lg_off','lg_spikes','dg_on','dg_off',
    'dg_spikes','gm_on','gm_off','gm_spikes','mg_on','mg_off','mg_spikes', 'blank1',
    'blank2', 'blank3']
  df = pd.DataFrame(proc_data.values(), columns=column_names, index=proc_data.keys())
  df = df.sort_index()
  return df


def allowed_file(filename):
  # Implements check of filename extensions specified in config.json
  allowed_exts = set(config['AllowedFiletypes'])
  return '.' in filename and filename.rsplit('.', 1)[1] in allowed_exts


def zipdir(path, zipf):
  for root, dirs, files in os.walk(path):
    for file in files:
      zipf.write(os.path.join(root, file))


@login_manager.user_loader
def load_user(user_id):
  # Populates user instance for Flask.Login user handling on login
  if user_id not in user_database:
    return
  user = User()
  user.id = user_id
  user.email = user_database[user_id][0]
  user.surname = user_database[user_id][1]
  user.lab = user_database[user_id][2]
  g.user = user
  return user


@login_manager.unauthorized_handler
def nope():
  # Flask redirects here when a @login_required page fails authentication check
  return render_template('unauthorized-page.html')


@app.route('/login', methods=['POST'])
def login():
  # Checks password and logs in user if credentials are valid
  form = LoginForm(request.form)
  if form.validate():
    user = load_user(form.username.data)
    if user is None:
      return render_template('/unauthorized-page.html')
    if hashlib.sha256(form.data['password']).hexdigest() \
        == user_pdatabase[user.id]:
      flask.ext.login.login_user(user)
      session['editusername'] = g.user.id
      return redirect(url_for('index'))
  return render_template('/unauthorized-page.html')


@app.route('/download-page')
def download_page():
  # Directs to download page
  if config['DownloadsAllowed'] != 1:
    return render_template('feature-disabled.html')
  return render_template('download-page.html')


@app.route('/dl-files-page', methods = ['GET', 'POST'])
def dl_files_page():
  # Directs to file download page
  if config['DownloadsAllowed'] != 1:
    return render_template('feature-disabled.html')
  metadata_df = MakeMetaDF(metadata)
  metadata_df = metadata_df.drop('Notes', axis=1)
  metadata_df = metadata_df.loc[metadata_df.loc[:,'Files']>1,:] 
  metadata_df.index = range(len(metadata_df))   
  if request.method == 'POST':
    form = FileDownloadForm(request.form)
    if form.data['identifier']>=0 and form.data['identifier']<len(metadata_df):
      session['exp_name'] = metadata_df.loc[form.data['identifier']]['User'] \
        +'-'+metadata_df.loc[form.data['identifier']]['Exp ID']
      return redirect(url_for('file_download'))
  table_html = metadata_df.to_html()
  form = FileDownloadForm()
  return render_template('dl-files-page.html', table_html=table_html, form=form)


#Following routes direct to various downloads, as described
@app.route('/dl-readme')
def dl_readme():
  return send_from_directory('.', 'README.md', as_attachment=True)   


@app.route('/dl-metadata-page')
def dl_metadata_page():
  if config['DownloadsAllowed'] != 1:
    return render_template('feature-disabled.html')
  metadata_df = MakeMetaDF(metadata)
  table_html = metadata_df.to_html()
  return render_template('dl-metadata-page.html', table_html=table_html)


@app.route('/dl-metadata-json')
def dl_metadata_json():
  metadata_df = MakeMetaDF(metadata)
  response = make_response(metadata_df.to_json())
  response.headers['Content-Disposition'] = 'attachment; filename=metadata.json'
  return response


@app.route('/dl-metadata-csv')
def dl_metadata_csv():
  metadata_df = MakeMetaDF(metadata)
  response = make_response(metadata_df.to_csv(index=False))
  response.headers['Content-Disposition'] = 'attachment; filename=metadata.csv'
  return response


@app.route('/dl-metadata-csv-nonotes')
def dl_metadata_csv_nonotes():
  metadata_df = MakeMetaDF(metadata)
  metadata_df = metadata_df.drop('Notes', axis=1)
  response = make_response(metadata_df.to_csv(index=False))
  response.headers['Content-Disposition'] = 'attachment; filename=metadata_nonotes.csv'
  return response

  
@app.route('/dl-procdata-page')
def dl_procdata_page():
  if config['DownloadsAllowed'] != 1:
    return render_template('feature-disabled.html')
  procdata_df = MakeCondDF(proc_data)
  procdata_df = procdata_df.dropna(axis=1, how='all')
  table_html = procdata_df.to_html()
  return render_template('dl-procdata-page.html', table_html=table_html)


@app.route('/dl-procdata-csv')
def dl_procdata_csv():
  procdata_df = MakeCondDF(proc_data)
  response = make_response(procdata_df.to_csv(index_label='cond_ID'))
  response.headers['Content-Disposition'] = 'attachment; filename=procdata.csv'
  return response


@app.route('/dl-procdata-json')
def dl_procdata_json():
  procdata_df = MakeCondDF(proc_data)
  response = make_response(procdata_df.to_json())
  response.headers['Content-Disposition'] = 'attachment; filename=procdata.json'
  return response 


@app.route('/upload-page', methods=['GET', 'POST'])
@login_required
def upload_page():
  """ 
  Also referred to as "experiment page".
  
  This function shows users their uploaded experiments and allows them to 
  edit or delete them, and also to create new experiments
  """ 
  if config['UploadsAllowed'] != 1:
    return render_template('feature-disabled.html')
  if user_database[g.user.id][3] == 0:
    return render_template('user-uploads-disabled.html')
  if request.method == 'GET':
    metadata_df=MakeMetaDF(metadata)
    if g.user.id != 'Admin':  # Admin can see all experiments
      metadata_df=metadata_df.loc[metadata_df.loc[:,'User']==g.user.id,:]
    metadata_df.index = range(len(metadata_df))   
    df_no_notes = metadata_df.drop('Notes', axis=1) # Don't show notes here
    table_html = df_no_notes.to_html()
    form = UploadActionForm()
    return render_template('upload-page.html', table_html=table_html, form=form)
  else:
    form = UploadActionForm(request.form)
    metadata_df=MakeMetaDF(metadata)
    if g.user.id != 'Admin':  
      metadata_df=metadata_df.loc[metadata_df.loc[:,'User']==g.user.id,:] 
    metadata_df.index = range(len(metadata_df))   
    if form.validate():   # Checks for valid form entry
      if form.data['identifier']<0 or form.data['identifier']>(len(metadata_df)-1) \
                    or form.data['identifier']==None:
        return render_template('upload-message.html', msg='Invalid identifier')
      session['exp_name'] = metadata_df.loc[form.data['identifier'], 'User'] \
        +'-'+metadata_df.loc[form.data['identifier'], 'Exp ID'] 
      if form.data['action'] == 'editP':
        return redirect(url_for('experiment_page'))
      if form.data['action'] == 'editM':
        return redirect(url_for('edit_metadata'))
      if form.data['action'] == 'delete':
        return redirect(url_for('delete_experiment'))
    else: # sends back to template with errors if form did not validate
      metadata_df=MakeMetaDF(metadata)
      if g.user.id != 'Admin':
        metadata_df=metadata_df.loc[metadata_df.loc[:,'User']==g.user.id,:] 
      metadata_df.index = range(len(metadata_df))
      df_no_notes = metadata_df.drop('Notes', axis=1)
      table_html = df_no_notes.to_html()      
      return render_template('upload-page.html', table_html=table_html, form=form)  


@app.route('/experiment-page', methods=['GET', 'POST'])
@login_required
def experiment_page():
  """
  This page allows editing of a particular experiment.
  
  This includes uploading associated files, editing metadata, or adding/editing/deleting
  conditions
  """ 
  if config['UploadsAllowed'] != 1:
    return render_template('feature-disabled.html')
  if user_database[g.user.id][3] == 0:
    return render_template('user-uploads-disabled.html')
  if not os.path.isdir(config['FilePath']+session['exp_name']):
    os.mkdir(config['FilePath']+session['exp_name'])  
  if not os.path.exists(config['FilePath']+session['exp_name']+'/READ_ME.txt'):
    read_me = open(config['FilePath']+session['exp_name']+'/READ_ME.txt', 'w')
    read_me.write('Auto-generated blank read_me for '+session['exp_name'])
    read_me.close()
    metadata[session['exp_name']][12] += 1
    with open('databases/metadata.json', 'w') as outfile:
      json.dump(metadata, outfile)    
  if request.method == 'GET':
    conditions_df = MakeCondDF(proc_data)
    conditions_df = conditions_df[conditions_df.index.str.contains(session['exp_name'])]
    conditions_df = conditions_df.sort_index()
    conditions_df.index = range(len(conditions_df))
    conditions_df = conditions_df.dropna(axis=1, how='all')
    table_html = conditions_df.to_html()
    form = ExperimentActionForm()   
    filenames = [str(filename) for filename in os.listdir(config['FilePath']+session['exp_name'])]
    metadata[session['exp_name']][12] = len(filenames)
    filecount = metadata[session['exp_name']][12]
    return render_template('experiment-page.html', table_html=table_html,
      filenames=filenames, filecount=filecount, form=form, name=session['exp_name'])
  if request.method == 'POST':
    form = ExperimentActionForm(request.form)
    if form.validate():
      if form.data['identifier']<0 or form.data['identifier']>metadata[session['exp_name']][11]:
        return render_template('experiment-message.html', msg='Invalid identifier')
      if form.data['action'] == 'edit':
        session['cond_num'] = str(form.data['identifier'])      
        session['cond_name'] = proc_data[session['exp_name']+'_'+session['cond_num']][0]
        return redirect(url_for('processed_data'))
      if form.data['action'] == 'delete':
        if form.data['identifier']==0:
          msg='You cannot delete baseline condition. Delete entire experiment.'
          return render_template('experiment-message.html', msg=msg)
        session['cond_num'] = str(form.data['identifier'])      
        session['cond_name'] = proc_data[session['exp_name']+'_'+session['cond_num']][0]          
        proc_data.pop(session['exp_name']+'_'+session['cond_num'])
        for condnum in range(form.data['identifier']+1, metadata[session['exp_name']][11]):
          proc_data[session['exp_name']+'_'+str(condnum-1)]=proc_data.pop(session['exp_name']+'_'+str(condnum))
        metadata[session['exp_name']][11]-=1
        with open('databases/metadata.json', 'w') as outfile:
          json.dump(metadata, outfile)
        with open('databases/processed_data.json', 'w') as outfile:
          json.dump(proc_data, outfile)
        msg='Condition '+session['cond_name']+' deleted.'
        return render_template('experiment-message.html', msg=msg)
    else:
      conditions_df = (proc_data)
      conditions_df = conditions_df[conditions_df.index.str.contains(session['exp_name'])]
      conditions_df = conditions_df.sort_index()
      conditions_df.index = range(len(conditions_df))
      conditions_df = conditions_df.dropna(axis=1, how='all')
      table_html = conditions_df.to_html()
      filenames = [str(filename) for filename in os.listdir(config['FilePath']+session['exp_name'])]
      filecount = metadata[session['exp_name']][12]
      return render_template('experiment-page.html', table_html=table_html,
        filenames=filenames, filecount=filecount, form=form, name=session['exp_name'])


@app.route('/file-upload', methods=['GET', 'POST'])
@login_required
def file_upload():
  # Manages file uploads
  if config['UploadsAllowed'] != 1:
    return render_template('feature-disabled.html')
  if user_database[g.user.id][3] == 0:
    return render_template('user-uploads-disabled.html')    
  if metadata[session['exp_name']][12] >= config['MaxFiles']:
    msg = 'Cannot upload more files, reached maximum for this experiment.'
    return render_template('file-upload-message.html', msg=msg)
  if request.method == 'GET':
    read_me_file = open(config['FilePath']+session['exp_name']+'/READ_ME.txt')
    form = ReadMeForm(read_me = read_me_file.read(10000))
    read_me_file.close()
    return render_template('file-upload-page.html', name=session['exp_name'], form=form)
  else:
    form = ReadMeForm(request.form)
    read_me_file = open(config['FilePath']+session['exp_name']+'/READ_ME.txt', 'w')
    read_me_file.write(form.data['read_me'])
    read_me_file.close()
    file = request.files['file']
    file.seek(0, os.SEEK_END)
    file_length = file.tell()
    if file_length > config['MaxFilesizeMB']*1e6:
      msg = 'Cannot upload, file too large'
      return render_template('file-upload-message.html', msg=msg)
    file.seek(0, os.SEEK_SET)
    if file and allowed_file(file.filename):
      filename = secure_filename(file.filename)
      filenames = os.listdir(config['FilePath']+session['exp_name'])
      if filename in filenames:
        return render_template('file-upload-message.html', msg='Filename already used.')
      file.save(config['FilePath']+session['exp_name']+'/'+filename)
      metadata[session['exp_name']][12]+=1
      with open('databases/metadata.json', 'w') as outfile:
        json.dump(metadata, outfile)
      msg = 'Successfully uploaded '+filename
      return render_template('file-upload-message.html', msg=msg)
    else:
      msg = 'Upload failed. File type is probably not allowed.'
      return render_template('file-upload-message.html', msg=msg) 


@app.route('/files-readme', methods=['GET', 'POST'])
@login_required
def files_readme():
  # Direct edit of read me file for files
  if request.method == 'GET':
    read_me_file = open(config['FilePath']+session['exp_name']+'/READ_ME.txt')
    form = ReadMeForm(read_me = read_me_file.read(10000))
    read_me_file.close()
    filenames = [str(filename) for filename in os.listdir(config['FilePath']+session['exp_name'])]
    return render_template('files-readme-page.html', form=form, filenames=filenames)
  else:
    form = ReadMeForm(request.form)
    read_me_file = open(config['FilePath']+session['exp_name']+'/READ_ME.txt', 'w')
    read_me_file.write(form.data['read_me'])
    read_me_file.close()
    return redirect(url_for('experiment_page'))


@app.route('/file-download', methods=['GET', 'POST'])
def file_download():
  # Manages file downloads
  if metadata[session['exp_name']][12] == 0:
    msg = 'No files to download.'
    return render_template('download-message.html', msg=msg)
  if request.method == 'GET':
    filenames = os.listdir(config['FilePath']+session['exp_name'])
    filenames_df = pd.DataFrame(filenames, columns=['Filename'])
    table_html = filenames_df.to_html()
    return render_template('file-download-page.html', table_html=table_html)
  else:
    home_dir = os.getcwd()
    if os.path.exists(config['FilePath']+'temp/'):
      rmtree(config['FilePath']+'temp/')
    os.mkdir(config['FilePath']+'temp')
    zipf = zipfile.ZipFile(config['FilePath']+'temp/'+session['exp_name']+'.zip', 'w')
    os.chdir(config['FilePath'])    
    zipdir(session['exp_name'], zipf)
    zipf.close()
    os.chdir(home_dir)
    return send_from_directory(config['FilePath']+'temp/', session['exp_name']+'.zip', as_attachment=True)   


@app.route('/file-delete', methods=['GET', 'POST'])
@login_required
def file_delete():
  # Manages file deletion
  if config['EditsAllowed'] != 1:
    return render_template('feature-disabled.html')
  if metadata[session['exp_name']][12] == 0:
    msg = 'No files to delete.'
    return render_template('file-upload-message.html', msg=msg)
  if request.method == 'GET':
    filenames = [str(filename) for filename in os.listdir(config['FilePath']+session['exp_name'])]
    filenames_df = pd.DataFrame(filenames, columns=['Filename'])
    table_html = filenames_df.to_html()
    form = FileDeleteForm()
    return render_template('file-delete-page.html', table_html=table_html, form=form)
  else:
    form = FileDeleteForm(request.form)
    if form.validate():
      filenames = os.listdir(config['FilePath']+session['exp_name'])
      filenames_df = pd.DataFrame(filenames, columns=['Filename'])
      if form.data['identifier'] >= len(filenames_df['Filename']) or form.data['identifier'] < 0:
        msg = 'Delete failed. Invalid identifier.'
        return render_template('file-upload-message.html', msg=msg)
      os.remove(config['FilePath']+session['exp_name']+'/'+filenames_df['Filename'][form.data['identifier']])
      metadata[session['exp_name']][12]-=1
      with open('databases/metadata.json', 'w') as outfile:
        json.dump(metadata, outfile)
      msg = 'File deleted.'
      return render_template('file-upload-message.html', msg=msg)
    else:
      filenames = [str(filename) for filename in os.listdir(config['FilePath']+session['exp_name'])]
      filenames_df = pd.DataFrame(filenames, columns=['Filename'])
      table_html = filenames_df.to_html()   
      return render_template('file-delete-page.html', table_html=table_html, form=form)


@app.route('/new-condition', methods=['GET', 'POST'])
@login_required
def new_condition():
  # From experiment page, adds a new condition
  if request.method == 'GET':
    form = NewConditionForm()
    return render_template('new-condition.html', form=form, name=session['exp_name'])
  if request.method == 'POST':
    form = NewConditionForm(request.form)
    if form.validate():
      session['cond_num'] = str(metadata[session['exp_name']][11])
      session['cond_name'] = form.data['name']
      proc_data[session['exp_name']+'_'+session['cond_num']] = [None]*33
      proc_data[session['exp_name']+'_'+session['cond_num']][0]=session['cond_name']
      metadata[session['exp_name']][11]+=1
      with open('databases/metadata.json', 'w') as outfile:
        json.dump(metadata, outfile)
      with open('databases/processed_data.json', 'w') as outfile:
        json.dump(proc_data, outfile)
      return redirect(url_for('processed_data'))
    else:
      return render_template('new-condition.html', form=form, name=session['exp_name'])


@app.route('/delete-experiment', methods=['GET', 'POST'])
@login_required
def delete_experiment():
  # From upload/experiments page, deletes experiment and files
  if config['EditsAllowed'] != 1:
    return render_template('feature-disabled.html')
  if user_database[g.user.id][3] == 0:
    return render_template('user-uploads-disabled.html')  
  if request.method == 'GET':
    form = DeleteForm()
    return render_template('delete-experiment.html', name=session['exp_name'], form=form)
  else:
    form = DeleteForm(request.form)
    if form.data['verify'] == 'DELETE':
      for condnum in range(metadata[session['exp_name']][11]):
        proc_data.pop(session['exp_name']+'_'+str(condnum))
      metadata.pop(session['exp_name']) 
      with open('databases/metadata.json', 'w') as outfile:
        json.dump(metadata, outfile)
      with open('databases/processed_data.json', 'w') as outfile:
        json.dump(proc_data, outfile)
      if os.path.isdir(config['FilePath']+session['exp_name']):
        rmtree(config['FilePath']+session['exp_name'])    
      msg='Deleted experiment '+session['exp_name']
      return render_template('upload-message.html', msg=msg)
    else:
      msg='Did not delete, DELETE was not received.'
      return render_template('upload-message.html', msg=msg)


@app.route('/new-experiment', methods=['GET', 'POST'])
@login_required
def new_experiment():
  # From experiments / upload page, defines a new experiment
  if config['UploadsAllowed'] != 1:
    return render_template('feature-disabled.html')
  if user_database[g.user.id][3] == 0:
    return render_template('user-uploads-disabled.html')    
  user_experiment_count = sum([g.user.id in key for key in metadata.keys()])
  if user_experiment_count >= config['MaxUserExperiments']:
    return render_template('upload-message.html',
      msg='You cannot create any more experiments (reached user maximum)')
  if request.method == 'GET':
    form = NewMetadataForm()
    return render_template('new-experiment.html', name=g.user.id, form=form)
  else:
    form = NewMetadataForm(request.form)
    if form.validate():
      if g.user.id+'-'+form.data['exp_id'] in metadata.keys():
        return render_template('upload-message.html', msg='Experiment ID already exists') 
      session['exp_name'] = g.user.id+'-'+form.data['exp_id'] 
      metadata[g.user.id+'-'+form.data['exp_id']] = [
        g.user.id, form.data['exp_id'], str(form.data['exp_date']),
        str(form.data['animal_date']), form.data['experimenter'],
        form.data['lab'], form.data['temp'], form.data['tanktemp'],
        form.data['species'], form.data['intra_sol'], form.data['saline'],
        1, 0, "", "", "", form.data['notes']]
      proc_data[g.user.id+'-'+form.data['exp_id']+'_0'] = [None]*33
      proc_data[g.user.id+'-'+form.data['exp_id']+'_0'][0]='baseline'
      with open('databases/metadata.json', 'w') as outfile:
        json.dump(metadata, outfile)
      with open('databases/processed_data.json', 'w') as outfile:
        json.dump(proc_data, outfile)
      session['cond_num'] = '0'
      session['cond_name'] = 'baseline'
      return redirect(url_for('checkboxes_page'))
    else:
      return render_template('new-experiment.html', name=g.user.id, form=form)


@app.route('/edit-metadata', methods=['GET', 'POST'])
@login_required
def edit_metadata():
  # From upload/experiments page, edits metadata for selected experiment
  if config['EditsAllowed'] != 1:
    return render_template('feature-disabled.html')
  if user_database[g.user.id][3] == 0:
    return render_template('user-uploads-disabled.html')    
  if request.method == 'GET':
    data = metadata[session['exp_name']]
    form = MetadataForm(experimenter=data[4], lab=data[5], temp=data[6],
         tanktemp=data[7], species=data[8], intra_sol=data[9],
         saline=data[10], notes=data[16], nerves=['a'])
    return render_template('edit-metadata.html', form=form, name=session['exp_name'],
      oldexpdate=data[2], oldandate=data[3])
  else:
    form = MetadataForm(request.form)
    if form.validate():
      metadata[session['exp_name']][2] = str(form.data['exp_date'])
      metadata[session['exp_name']][3] = str(form.data['animal_date'])
      metadata[session['exp_name']][4] = form.data['experimenter']
      metadata[session['exp_name']][5] = form.data['lab']
      metadata[session['exp_name']][6] = form.data['temp']
      metadata[session['exp_name']][7] = form.data['tanktemp']
      metadata[session['exp_name']][8] = form.data['species']
      metadata[session['exp_name']][9] = form.data['intra_sol']
      metadata[session['exp_name']][10] = form.data['saline']
      metadata[session['exp_name']][16] = form.data['notes']
      with open('databases/metadata.json', 'w') as outfile:
        json.dump(metadata, outfile)
      return redirect(url_for('checkboxes_page'))
    else:
      return render_template('edit-metadata.html', name=session['exp_name'], form=form)


@app.route('/checkboxes-page', methods=['GET', 'POST'])
@login_required
def checkboxes_page():
  if request.method == 'GET':
    if metadata[session['exp_name']][13] is None:
        nerves = None
    else:
        nerves = metadata[session['exp_name']][13].split('; ')
    if metadata[session['exp_name']][14] is None:
        neurons = None
    else:
        neurons = metadata[session['exp_name']][14].split('; ')    
    if metadata[session['exp_name']][15] is None:
        flags = None
    else:
        flags = metadata[session['exp_name']][15].split('; ')        
    form = CheckboxesForm(nerves=nerves, neurons=neurons, flags=flags)
    return render_template('checkboxes-page.html', form=form, name=session['exp_name'])
  else:
    form = CheckboxesForm(request.form)
    if form.data['nerves'] is None:
      metadata[session['exp_name']][13] = ''
    else:
      metadata[session['exp_name']][13] = str('; '.join(form.data['nerves']))
    if form.data['neurons'] is None:
      metadata[session['exp_name']][14] = ''
    else:
      metadata[session['exp_name']][14] = str('; '.join(form.data['neurons']))
    if form.data['flags'] is None:
      metadata[session['exp_name']][15] = ''
    else:
      metadata[session['exp_name']][15] = str('; '.join(form.data['flags']))
    with open('databases/metadata.json', 'w') as outfile:
      json.dump(metadata, outfile)
    return redirect(url_for('experiment_page'))


@app.route('/processed-data', methods=['GET', 'POST'])
@login_required
def processed_data():
  if config['EditsAllowed'] != 1:
    return render_template('feature-disabled.html')
  if user_database[g.user.id][3] == 0:
    return render_template('user-uploads-disabled.html')    
  if request.method == 'GET':
    data = proc_data[session['exp_name']+'_'+session['cond_num']]
    form = ProcessedDataForm(exp_temp=data[1], pyl_hz=data[2], pyl_cycvar=data[3], pyl_niqr=data[4],
      gas_hz=data[5], gas_cycvar=data[6], gas_niqur=data[7], pd_off=data[8],
      pd_spikes=data[9], lp_on=data[10], lp_off=data[11], lp_spikes=data[12],
      py_on=data[13], py_off=data[14], py_spikes=data[15], vd_on=data[16],
      vd_off=data[17], vd_spikes=data[18], lg_off=data[19], lg_spikes=data[20],
      dg_on=data[21], dg_off=data[22], dg_spikes=data[23], gm_on=data[24],
      gm_off=data[25], gm_spikes=data[26], mg_on=data[27], mg_off=data[28],
      mg_spikes=data[29], blank1=data[30], blank2=data[31], blank3=data[32])
    return render_template('processed-data.html', form=form, name=session['exp_name'], cond=session['cond_name'])
  else:
    form = ProcessedDataForm(request.form)
    if form.validate():
      proc_data[session['exp_name']+'_'+session['cond_num']] = [session['cond_name'],
        form.data['exp_temp'], form.data['pyl_hz'],
        form.data['pyl_cycvar'], form.data['pyl_niqr'], form.data['gas_hz'],
        form.data['gas_cycvar'], form.data['gas_niqr'], form.data['pd_off'],
        form.data['pd_spikes'], form.data['lp_on'], form.data['lp_off'],
        form.data['lp_spikes'], form.data['py_on'], form.data['py_off'],
        form.data['py_spikes'], form.data['vd_on'], form.data['vd_off'],
        form.data['vd_spikes'], form.data['lg_off'], form.data['lg_spikes'],
        form.data['dg_on'], form.data['dg_off'], form.data['dg_spikes'],
        form.data['gm_on'], form.data['gm_off'], form.data['gm_spikes'],
        form.data['mg_on'], form.data['mg_off'], form.data['mg_spikes'],
        form.data['blank1'], form.data['blank2'], form.data['blank3']]
      with open('databases/processed_data.json', 'w') as outfile:
        json.dump(proc_data, outfile)
      return redirect(url_for('experiment_page'))
    else:
      return render_template('processed-data.html', form=form, name=session['exp_name'], cond=session['cond_name'])


@app.route('/new-user', methods=['GET', 'POST'])
def new_user():
  # Create new user
  if config['NewUsersAllowed'] != 1:
    return render_template('feature-disabled.html')
  if request.method == 'GET':
    # get new user information, then come back as a post
    if len(user_database) > (config['MaxUsers']-1):
      return render_template('too-many-users.html')
    form = NewUserForm()
    return render_template('new-user.html', form=form)
  else:
    # create the user with validated user information
    form = NewUserForm(request.form)
    if form.validate():
      if form.data['username'] in user_database.keys():
        return render_template('username-collision.html')
      user_database[form.data['username']] = \
        [form.data['email'], form.data['surname'],
        form.data['lab'], 0]  # Trailing 0 sets upload flag to false for new users
      user_pdatabase[form.data['username']] = \
        (hashlib.sha256(form.data['password']).hexdigest())
      with open('databases/user_database.json', 'w') as outfile:
        json.dump(user_database, outfile)
      with open('databases/user_pdatabase.json', 'w') as outfile:
        json.dump(user_pdatabase, outfile)
      user = load_user(form.data['username'])
      session['editusername'] = form.data['username']
      flask.ext.login.login_user(user)
      return redirect(url_for('index'))
    else:     
      return render_template('new-user.html', form=form)


@app.route('/edit-user', methods=['GET', 'POST'])
@login_required
def edit_user():
  if request.method == 'GET':
    # get old user information, then come back as a post
    form = EditUserForm(surname=user_database[session['editusername']][1], \
      email=user_database[session['editusername']][0], \
      lab=user_database[session['editusername']][2])
    return render_template('edit-user.html', form=form, name=session['editusername'])
  else:
    # re-save the user with validated user information
    form = EditUserForm(request.form)
    if form.validate():
      user_database[session['editusername']] = \
        [form.data['email'], form.data['surname'],
        form.data['lab']]
      with open('databases/user_database.json', 'w') as outfile:
        json.dump(user_database, outfile)
      return redirect(url_for('index'))
    else:
      return render_template('edit-user.html', form=form, name=session['editusername'])


@app.route('/password-change', methods=['GET', 'POST'])
@login_required
def password_change():
  if request.method == 'GET':
    # get new password, then come back as a post
    form = PasswordChangeForm()
    return render_template('password-change.html', form=form, msg=session['editusername']+' password change')
  else:
    # re-save the user's hashed new password with validated user information
    form = PasswordChangeForm(request.form)
    if hashlib.sha256(form.data['oldpassword']).hexdigest() \
        != user_pdatabase[session['editusername']]:
      return render_template('password-change.html', form=form,
        msg='Wrong password for '+session['editusername'])
    if not form.validate():
      return render_template('password-change.html', form=form,
        msg=session['editusername']+' password change')           
    else:
      user_pdatabase[session['editusername']] = \
        (hashlib.sha256(form.data['password']).hexdigest())
      with open('databases/user_pdatabase.json', 'w') as outfile:
        json.dump(user_pdatabase, outfile)  
      return redirect(url_for('index'))


@app.route('/admin-page', methods=['GET', 'POST'])
@login_required
def admin_page():
  # Manages administrator control over users, including deletion and upload activation
  if g.user.id != "Admin":
    return redirect(url_for('index'))
  if request.method == "GET":
    users_df = MakeDF(user_database, ['Email', 'Surname', 'Lab', 'UploadFlag'])
    for username in user_database.keys():
      users_df.loc[username, 'Experiments'] = sum([username in key for key in metadata.keys()])
    table_html = users_df.to_html()
    form = AdminActionForm()
    return render_template('admin-page.html', table_html=table_html, \
      form=form)
  else:
    form = AdminActionForm(request.form)
    users_df = MakeDF(user_database, ['Email', 'Surname', 'Lab', 'UploadFlag'])
    if not form.validate():
      table_html = users_df.to_html()
      return render_template('admin-page.html', \
        table_html=table_html, form=form)
    if form.data['username'] not in user_database.keys():
      msg = 'User not found'
      return render_template('admin-message.html', msg=msg)   
    if form.data['action'] == 'delete':
      if form.data['username'] == "Admin":
        msg = 'You cannot delete Admin, Admin.'
      else:
        user_database.pop(form.data['username'])
        user_pdatabase.pop(form.data['username'])
        with open('databases/user_database.json', 'w') as outfile:
          json.dump(user_database, outfile)
        with open('databases/user_pdatabase.json', 'w') as outfile:
          json.dump(user_pdatabase, outfile)
        msg = 'User ' + form.data['username'] + ' deleted.'
      return render_template('admin-message.html', msg=msg)
    if form.data['action'] == 'edit':
      session['editusername'] = form.data['username']
      form = EditUserForm(surname=user_database[session['editusername']][1], \
        email=user_database[session['editusername']][0], \
        lab=user_database[session['editusername']][2])
      return render_template('edit-user.html', form=form, name=session['editusername'])
    if form.data['action'] == 'password':
      new_random_password = ''.join(
        random.choice(string.ascii_letters + string.digits) for _ in range(8))
      user_pdatabase[form.data['username']] = \
        (hashlib.sha256(new_random_password).hexdigest())
      with open('databases/user_pdatabase.json', 'w') as outfile:
        json.dump(user_pdatabase, outfile)
      msg = ('Password for '+form.data['username']+' set to '+new_random_password)
      msg2 = ('\nPlease email this password to '+user_database[form.data['username']][0])
      return render_template('admin-message.html', msg=msg+msg2)
    if form.data['action'] == 'activate':
      user_database[form.data['username']][3] = 1
      with open('databases/user_database.json', 'w') as outfile:
        json.dump(user_database, outfile)
      return render_template('admin-message.html',
        msg=form.data['username']+' can now upload data.')      
    if form.data['action'] == 'deactivate':
      user_database[form.data['username']][3] = 0
      with open('databases/user_database.json', 'w') as outfile:
        json.dump(user_database, outfile)
      return render_template('admin-message.html',
        msg=form.data['username']+' can no longer upload data.')


@app.route('/')
def index():
  if os.path.exists('temp/'):
    rmtree('temp/')
  return render_template('index.html', emailaddress = user_database['Admin'][0])


@app.route('/sign-in')
def sign_in():
  form = LoginForm()
  return render_template('sign-in.html', form=form)


@app.route('/sign-out')
def sign_out():
  flask.ext.login.logout_user()
  return render_template('sign-out.html')


# Execution starts here
# Do not run in debug mode if allowing external connections! Security risk.

if __name__ == '__main__':
  app.config["SECRET_KEY"] = "ITSASECRET"
  port = int(os.environ.get("PORT", 80))
  app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
  # Enable this line (instead of the above) to use https: with an ad-hoc certificate:
  # app.run(host='0.0.0.0', port=port, debug=False, ssl_context='adhoc')
