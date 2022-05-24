import json
import logging
import os

from flask import Blueprint, render_template, current_app, url_for, request, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import redirect

from app.blueprints.forms import UploadDatasetForm
from app.blueprints.util import load_data, delete_data, get_clustering_info
from app.db import db
from app.model import Dataset
from app.util import ensure_exists_folder

dashboard = Blueprint('dashboard', __name__)
log = logging.getLogger()


@dashboard.route('/dashboard')
@login_required
def index():
    return render_template('dashboard/index.html')


@dashboard.route('/dashboard/datasets', methods=['GET', 'POST'])
@login_required
def datasets():
    # Upload form
    owner = current_user.id
    form = UploadDatasetForm(owner)
    if form.validate_on_submit():

        # Create dataset object from inputs
        # columns = pd.read_csv(f, header=0, nrows=0).columns.tolist()
        name = form.name.data
        description = form.description.data
        label_column = form.label_column.data
        prediction_column = form.prediction_column.data
        new_dataset = Dataset(name=name, owner=owner, description=description, label_column=label_column,
                              prediction_column=prediction_column)

        # Add dataset object to database
        db.session.add(new_dataset)
        db.session.commit()
        log.debug(f"Added {new_dataset} to database")

        # Ensure user has an upload folder already
        user_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], owner)
        ensure_exists_folder(user_folder)

        # Save data file in user_folder
        f = form.dataset.data
        file_path = os.path.join(user_folder, new_dataset.id + '.csv')
        f.seek(0)  # to avoid storing an empty file
        f.save(file_path)
        if not os.path.exists(file_path):
            db.session.delete(new_dataset)
            db.session.commit()
            # TODO report error to user
            log.debug(f"Could not save file '{file_path}'!")
        else:
            log.debug(f"Saved file '{file_path}'!")

        # Redirect to same page (to clear form inputs)
        return redirect(url_for('dashboard.datasets'))

    # Get all the user's datasets
    dataset_list = Dataset.query.filter_by(owner=owner)

    return render_template('dashboard/datasets.html', form=form, datasets=dataset_list)


@dashboard.route('/dashboard/datasets/delete', methods=['POST'])
@login_required
def delete_dataset():
    # Get selected datasets
    owner = current_user.id
    selected_names = json.loads(request.form.get('datasets'))
    datasets = Dataset.query.filter_by(owner=owner).filter(Dataset.name.in_(selected_names)).all()

    # Remove selected datasets from database & remove data files from disk
    for d in datasets:
        log.debug(f"Delete dataset {d}...")
        db.session.delete(d)
        db.session.commit()

        delete_data(owner, d.id)
        log.debug(f"Deleted dataset!")

    return redirect(url_for('dashboard.datasets'))


@dashboard.route('/dashboard/inspect', methods=['GET', 'POST'])
@login_required
def inspect():
    # Either get dataset from request via name (POST) or simply the latest uploaded (GET)
    selected_name = request.form.get('dataset')
    all_datasets = Dataset.query.filter_by(owner=current_user.id).order_by(Dataset.upload_date.desc()).all()

    if selected_name is None:
        # Most recent uploaded (first in list)
        dataset = all_datasets[0]
        # TODO no dataset uploaded
    else:
        # Get dataset by name
        for d in all_datasets:
            if d.name == selected_name:
                dataset = d
        # TODO dataset name does not match any of the datasets

    # Load data columns+types (cached)
    columns = load_data(current_user.id, dataset.id).dtypes  # TODO try catch
    # log.debug(f"{type(columns)}: {columns}")

    # TODO fix missing icons
    return render_template('dashboard/inspect.html', all_datasets=all_datasets, dataset=dataset, columns=columns)


@dashboard.route('/dashboard/datasets/<name>')
@login_required
def raw_data(name):
    # Get query parameters limit, offset, sort, order and filter TODO check for valid inputs?
    # log.debug(request.args)
    offset = request.args.get('offset')  # might be None
    offset = int(offset) if offset else 0  # parse str to int or 0 if None
    limit = request.args.get('limit')
    limit = int(limit) if limit else 10
    sort = request.args.get('sort')
    order = request.args.get('order')
    filter = request.args.get('filter')

    # Query dataset object from database and load data
    d = Dataset.query.filter_by(owner=current_user.id, name=name).first_or_404()
    data = load_data(current_user.id, d.id)  # TODO try catch

    # Apply filter
    if filter:
        log.debug(f"Filter {filter} {type(filter)}")
        filter = json.loads(filter)
        log.debug(f"Filter {filter} {type(filter)}")
        for c, f in filter.items():
            data = data[data[c].astype(str).str.contains(f)]

    # Paginate & sort loaded data
    total_rows = len(data)
    if sort and order:
        data = data.sort_values(by=sort, ascending=(order == 'asc'))
    data = data.iloc[offset:offset + limit]

    # Prepare json from dataframe
    data_json = data.to_json(orient='records')
    parsed = json.loads(data_json)  # list of records (dicts with column:value pairs)

    # server-side pagination requires format {'total': num, 'rows': {... dataframe ...}}
    server_side_format = {'total': total_rows, 'rows': parsed}

    return json.dumps(server_side_format, indent=4)


@dashboard.route('/dashboard/datasets/columns')
@login_required
def raw_data_columns():
    id = request.args.get('id')  # might be None
    d = Dataset.query.filter_by(owner=current_user.id, id=id).first_or_404()
    columns = load_data(current_user.id, d.id).dtypes # TODO try catch
    columns = columns.drop([d.label_column, d.prediction_column])
    return columns.to_json(default_handler=str)  # default handler to fix recursion OverflowError


@dashboard.route('/dashboard/fairness', methods=['GET', 'POST'])
@login_required
def fairness():
    # Get all the user's datasets   # TODO no datasets available
    all_datasets = Dataset.query.filter_by(owner=current_user.id).order_by(Dataset.name).all()

    # Display progress/results of fairness analysis task on POST request
    if request.method == 'POST':
        pass

    return render_template('dashboard/fairness.html', all_datasets=all_datasets)


@dashboard.route('/dashboard/clustering')
def clustering_info():
    info = get_clustering_info()
    log.debug(info)
    log.debug(jsonify(info).json)
    return info
