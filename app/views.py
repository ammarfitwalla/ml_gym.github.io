import ast
import glob
import json
import uuid
import shutil
import pickle
import mimetypes
from .utils import *
import seaborn as sns
from app.models import *
import category_encoders as ce
from django.contrib import messages
from pandas.api.types import is_string_dtype
from sklearn.preprocessing import StandardScaler, LabelEncoder
from django.utils.text import get_valid_filename
from sklearn import metrics, utils, preprocessing
from sklearn.model_selection import train_test_split
from django.core.files.storage import FileSystemStorage
from django.contrib.auth import authenticate, login, logout, decorators
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render, HttpResponse, redirect, get_object_or_404

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

# logger = logging.getLogger(__name__)

media_path = settings.MEDIA_ROOT
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
list_to_handle_nan_values = ['mean', 'median', 'bfill', 'ffill', 0, 'delete records']
list_to_handle_nan_str_values = ['bfill', 'ffill', 0, 'delete records']

plt.switch_backend('agg')


def home(request):
    return render(request, 'home.html')


def continue_as_guest(request):
    request.session['guest_session_id'] = str(uuid.uuid4())
    return redirect('/upload/')


def sign_up(request):
    if request.method == "POST":
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')

        # ============== VALIDATIONS ============== #
        if User.objects.filter(username=username).exists():
            messages.warning(request, 'Username already present, please choose different username')
            return redirect('/signup/')

        if len(username) > 10:
            messages.warning(request, "Username must be below 10 characters")
            return redirect('/signup/')

        if not username.isalnum():
            messages.warning(request, "Username must be Alphanumeric only")
            return redirect('/signup/')

        if User.objects.filter(email=email).exists():
            messages.warning(request, "Email already present")
            return redirect('/signup/')

        user = User.objects.create_user(username, email, password)
        user.save()

        custom_user = Profile(user=user)
        custom_user.save()
        user = authenticate(username=username, password=password)
        login(request, user)
        messages.success(request, 'Account created, Successfully Logged in')
        try:
            user_ip = get_client_ip(request)
            data_dict = get_user_info(user_ip)
            write_user_info_to_excel(data_dict)
        except Exception as e:
            pass
        return redirect('/upload/')

    return render(request, 'signup.html')


def login_page(request):
    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, 'Successfully Logged in')
            return redirect('/upload/')
        else:
            messages.error(request, 'Invalid Credentials')
            return redirect('/signin/')
    return render(request, 'login.html')


def logout_page(request):
    logout(request)
    messages.success(request, "Successfully logged out")
    return redirect('/signin/')


def download_file(request, filename):
    filepath = BASE_DIR + '/downloadapp/Files/' + filename
    path = open(filepath, 'r')
    mime_type, _ = mimetypes.guess_type(filepath)
    response = HttpResponse(path, content_type=mime_type)
    response['Content-Disposition'] = "attachment; filename=%s" % filename
    return response


def upload(request):
    if 'guest_session_id' not in request.session and not request.user.is_authenticated:
        return redirect('/signin/')

    elif request.method == 'POST':
        user = str(request.user.id) if request.user.id else request.session['guest_session_id']
        check_dir_exists(media_path + os.sep + user)
        check_dir_exists(media_path + os.sep + user + os.sep + 'documents')
        check_dir_exists(media_path + os.sep + user + os.sep + 'documents' + os.sep + 'input_files')

        if 'custom_file' in request.POST:
            if os.path.exists(media_path + os.sep + user + os.sep + 'documents' + os.sep + 'oh_encoder.json'):
                os.remove(media_path + os.sep + user + os.sep + 'documents' + os.sep + 'oh_encoder.json')

            my_file = request.FILES.get('myFile')
            if my_file:
                if os.path.splitext(my_file.name)[-1] == ".csv":
                    fs = FileSystemStorage(
                        location=media_path + os.sep + user + os.sep + 'documents' + os.sep + 'input_files' + os.sep)
                    my_file.name = get_valid_filename(my_file.name)
                    fs.save(my_file.name, my_file)
                    messages.success(request, 'File Uploaded')
                    return redirect('/eda/')
                else:
                    messages.error(request, 'Please select valid file with extension .csv')
                    return redirect('/upload/')
            else:
                messages.error(request, 'Please upload csv file, then click on Upload')
                return redirect('/upload/')

        elif '_download' in list(request.POST.keys())[-1]:
            name = list(request.POST.keys())[-1]
            filename = name.split("_download")[0]
            filepath = media_path + os.sep + 'sample_csv' + os.sep + filename
            path = open(filepath, 'r')
            mime_type, _ = mimetypes.guess_type(filepath)
            response = HttpResponse(path, content_type=mime_type)
            response['Content-Disposition'] = "attachment; filename=%s" % filename
            path.close()
            return response
        else:
            shutil.copy(media_path + os.sep + 'sample_csv' + os.sep + list(request.POST.keys())[-1],
                        media_path + os.sep + user + os.sep + 'documents' + os.sep + 'input_files')
            return redirect('/eda/')

    return render(request, 'upload.html')


# @decorators.login_required
def eda(request):
    if 'guest_session_id' not in request.session and not request.user.is_authenticated:
        return redirect('/signin/')

    user = request.user.id if request.user.id else request.session['guest_session_id']

    if user is not None:
        strong_positive = []
        moderate_positive = []
        strong_negative = []
        moderate_negative = []
        file_path = media_path + os.sep + str(user) + os.sep + 'documents' + os.sep + 'input_files'
        list_of_files = glob.glob(file_path + os.sep + '*')

        if not list_of_files:
            return redirect('/upload/')

        file_name = max(list_of_files, key=os.path.getmtime)
        df = file_to_df(file_name)

        pd.set_option('display.precision', 2)
        pd.set_option('display.float_format', lambda x: '%.2f' % x)

        df_n_rows, df_n_cols = df.shape[0], df.shape[1]
        df_cols = df.columns.tolist()
        missing_percentage = (df.isnull().sum() / len(df)) * 100

        # if missing_percentage.max() == 0:
        #     missing_value_message = "Great news! There are no missing values in the dataset."
        # else:
        #     missing_value_message = "% of missing data in columns:\n"
        #     for index, (column, percentage) in enumerate(missing_percentage.iteritems()):
        #         if percentage > 0:
        #             missing_value_message += f"{column}: {percentage:.2f}%"
        #             if index < len(missing_percentage) - 1:
        #                 missing_value_message += ", "
        #             else:
        #                 missing_value_message += "\n"

        if missing_percentage.max() == 0:
            missing_value_message = None
        else:
            missing_value_message = round(missing_percentage.mean(), 2)

        df_describe = df.describe()
        df_describe_html = df_describe.to_html(classes="table table-bordered table-striped table-hover custom-table",
                                               table_id="dfDescribeTable")

        # df_html = divide_columns_into_df(df.sample(20))
        # df_html = [i.to_html(classes="table table-bordered table-striped table-hover custom-table", index=False) for i
        #            in df_html]
        df_html = df.sample(100) if len(df) >= 100 else df.sample(len(df))
        df_html_json = df_html.values.astype(str).tolist()
        df_html_columns = df_html.columns.astype(str).to_list()
        df_html = df_html.to_html(
            classes="table table-bordered table-striped table-hover custom-table",
            index=False, table_id="dfTable")

        # items_per_page = 10
        # paginator = Paginator(df_html, items_per_page)
        # page_number = request.GET.get('page', 1)
        # print(page_number)
        # try:
        #     paginated_df = paginator.page(page_number)
        # except PageNotAnInteger:
        #     paginated_df = paginator.page(1)
        # except EmptyPage:
        #     paginated_df = paginator.page(paginator.num_pages)

        all_categorical = [col for col in df.columns if 1 < df[col].nunique() < 15]

        folder = media_path + os.sep + str(user) + os.sep + 'graphs'
        check_dir_exists(folder)

        sns.set(style="whitegrid")

        png_files_path = []
        a4_dims = (11.7, 8.27)

        for i in all_categorical:
            plt.subplots(figsize=a4_dims)

            ax = sns.countplot(x=df[i], data=df, palette="Set2")

            if df[i].nunique() > 5:
                ax.set_xticklabels(ax.get_xticklabels(), rotation=25)

            for p in ax.patches:
                ax.annotate('{:.1f}'.format(p.get_height()), (p.get_x(), p.get_height() + 5))

            png_file_name = folder + os.sep + f"{i}.png"
            plt.savefig(png_file_name, bbox_inches='tight', pad_inches=0.1, dpi=300)
            plt.close()

            png_files_path.append(png_file_name)

        try:
            df_corr = df.copy(deep=True)
            if all_categorical:
                label_encoder = LabelEncoder()
                for column in all_categorical:
                    df_corr[column] = label_encoder.fit_transform(df_corr[column])

            data_corr = df_corr.corr()
            checked_pairs = set()

            strong_positive = []
            moderate_positive = []
            strong_negative = []
            moderate_negative = []

            for col1 in data_corr.columns:
                for col2 in data_corr.columns:
                    if col1 != col2 and (col1, col2) not in checked_pairs and (col2, col1) not in checked_pairs:
                        correlation_value = data_corr.loc[col1, col2] * 100

                        if correlation_value > 70:
                            strong_positive.append({'pair': (col1, col2), 'value': correlation_value})
                        elif correlation_value > 50:
                            moderate_positive.append({'pair': (col1, col2), 'value': correlation_value})
                        elif correlation_value < -70:
                            strong_negative.append({'pair': (col1, col2), 'value': correlation_value})
                        elif correlation_value < -50:
                            moderate_negative.append({'pair': (col1, col2), 'value': correlation_value})

                        # Add the pair to the checked set to avoid redundant explanations
                        checked_pairs.add((col1, col2))

            f, ax = plt.subplots(figsize=a4_dims)
            if len(data_corr.columns.tolist()) < 15:
                sns.heatmap(data_corr, cmap='Blues', annot=True, fmt=".2f", cbar=True, linewidths=.5)
            else:
                sns.heatmap(data_corr, cmap='Blues', linewidths=.5)
            plt.title("Correlation Matrix", weight='bold', fontsize=15)
            correlation_name = folder + os.sep + 'correlation.png'
            plt.savefig(correlation_name, bbox_inches='tight', dpi=300)
            png_files_path.append(correlation_name)

        except Exception as err:
            print(f"[ERROR PLOTTING]: Unable to plot the heatmap due to: {str(err)}")

        if request.method == 'POST':
            return redirect('/data_preprocessing/')

        context = {'missing_value_message': missing_value_message, 'df_html': df_html, 'df_n_rows': df_n_rows,
                   'df_n_cols': df_n_cols, 'df_cols': df_cols, 'df_describe_html': df_describe_html,
                   'png_files_path': png_files_path, "df_html_columns": df_html_columns, 'df_html_json': df_html_json,
                   'strong_positive': strong_positive, 'moderate_positive': moderate_positive,
                   'strong_negative': strong_negative, 'moderate_negative': moderate_negative, }
        return render(request, "eda.html", context)
    else:
        return redirect('/signin/')


def advanced_eda(request):
    return render(request, 'advanced_eda.html')


# @decorators.login_required
def data_preprocessing(request):
    if 'guest_session_id' not in request.session and not request.user.is_authenticated:
        return redirect('/signin/')

    user = request.user.id if request.user.id else request.session['guest_session_id']
    docs_path = media_path + os.sep + str(user) + os.sep + 'documents'
    file_path = docs_path + os.sep + 'input_files'
    list_of_files = glob.glob(file_path + os.sep + '*')

    if not list_of_files:
        return redirect('/upload/')

    file_name = max(list_of_files, key=os.path.getmtime)  # TODO : NEED TO FIX
    df_preprocessing = file_to_df(file_name)

    df_col_numbers = df_preprocessing.shape[1]
    df_col_names = df_preprocessing.columns.tolist()
    df_null_columns, all_null_columns, string_cols, string_cols_null_count, numerical_cols_null_count = [], [], [], [], []
    df_null = df_preprocessing.isnull().values.any()

    if df_null:
        all_null_columns = df_preprocessing.columns[df_preprocessing.isna().any()].tolist()
        for i in all_null_columns:
            nan_count = " (" + str(df_preprocessing[i].isna().sum()) + " Rows)"
            if is_string_dtype(df_preprocessing[i]):
                string_cols.append(i)
                string_cols_null_count.append(nan_count)
            else:
                df_null_columns.append(i)
                numerical_cols_null_count.append(nan_count)

        string_cols = zip(string_cols, string_cols_null_count) if string_cols else None
        df_null_columns = zip(df_null_columns, numerical_cols_null_count) if df_null_columns else None

    if request.method == 'POST':
        dependent_variable = request.POST['dep_var_name']

        slider_value = request.POST['slider_value']
        test_size_ratio = (100 - int(slider_value)) / 100
        categorical_col_names = [col for col in df_preprocessing.columns if
                                 df_preprocessing[col].dtype == 'O' and df_preprocessing[col].nunique() < 15]

        if df_null:
            for i in all_null_columns:
                way = request.POST.get(i)
                if way == '0':
                    df_preprocessing[i] = df_preprocessing[i].fillna(0)
                elif way == 'bfill' or way == 'ffill':
                    df_preprocessing[i] = df_preprocessing[i].fillna(method=way)
                elif way == 'delete records':
                    df_preprocessing.dropna(subset=[i], inplace=True)
                elif way == 'mean':
                    df_preprocessing[i] = df_preprocessing[i].fillna((df_preprocessing[i].mean()))
                elif way == 'median':
                    df_preprocessing[i] = df_preprocessing[i].fillna((df_preprocessing[i].median()))

        selected_check_list = request.POST.getlist('checkbox_name')
        oh_encoder = ce.OrdinalEncoder(cols=categorical_col_names, handle_missing='error')
        df_preprocessing = oh_encoder.fit_transform(df_preprocessing)

        oh_encoder_dict = {}
        for i in oh_encoder.get_params()['mapping']:
            temp_dict = i['mapping'].to_dict()
            temp_dict_in_str = json.dumps(temp_dict)
            temp_dict_lowercase = json.loads(temp_dict_in_str.lower())
            oh_encoder_dict[i['col']] = temp_dict_lowercase

        with open(docs_path + os.sep + "oh_encoder.json", "w") as outfile:
            json.dump(oh_encoder_dict, outfile)

        if dependent_variable not in selected_check_list and df_col_numbers - len(selected_check_list) > 1:
            for column in df_preprocessing:
                if column not in selected_check_list and column not in categorical_col_names:
                    column_type = pd.api.types.infer_dtype(df_preprocessing[column])
                    if column_type == 'string':
                        selected_check_list.append(column)
            df_preprocessing = df_preprocessing.drop(selected_check_list, axis=1)
            df_preprocessing.to_csv(
                media_path + os.sep + str(user) + os.sep + 'documents' + os.sep + 'df_preprocessed.csv')
            d = {'dependent_variable': dependent_variable, 'test_size_ratio': test_size_ratio,
                 'dependent_variable_type': str(df_preprocessing.dtypes[dependent_variable])}

            with open(media_path + os.sep + str(user) + os.sep + 'documents' + os.sep + "df_preprocessed.json",
                      "w") as outfile:
                json.dump(d, outfile)

            return redirect('/model_selection/')
        elif df_col_numbers - len(selected_check_list) <= 1:
            messages.error(request, 'You cannot delete all the columns')
        else:
            messages.error(request, 'You cannot delete prediction column')

    context = {'df_null': df_null, 'nan_columns': df_null_columns,
               'string_cols': string_cols, 'list_handle_nan_values': list_to_handle_nan_values,
               'list_handle_nan_str_values': list_to_handle_nan_str_values, 'df_cols': df_col_names}

    return render(request, 'data_preprocessing.html', context)


# @decorators.login_required
def model_selection(request):
    all_ml_models = ['(AutoML) Regression', 'Linear Regression', '(AutoML) Classification', 'Logistic Regression',
                     'Decision Tree Classifier', 'KNeighbors Classifier', 'Random Forest Classifier',
                     'GaussianNB Classifier', 'SGD Classifier']
    if 'guest_session_id' not in request.session and not request.user.is_authenticated:
        return redirect('/signin/')

    user = str(request.user.id) if request.user.id else request.session['guest_session_id']
    # if request.is_ajax():
    #     print('AJAX REQUEST')
    #     data = request.GET.get('data')
    classifier = False

    docs_path = media_path + os.sep + user + os.sep + 'documents'
    if not os.path.isfile(docs_path + os.sep + 'df_preprocessed.csv'):
        return redirect('/upload/')
    df_model = pd.read_csv(docs_path + os.sep + 'df_preprocessed.csv')
    df_model.drop(columns=df_model.columns[0], axis=1, inplace=True)
    file = open(docs_path + os.sep + 'df_preprocessed.json')
    json_file = json.load(file)
    file.close()
    dependent_variable = json_file['dependent_variable']
    test_size_ratio = json_file['test_size_ratio']

    oh_encoders_json_file = None
    if os.path.isfile(docs_path + os.sep + 'oh_encoder.json'):
        oh_encoders_file = open(docs_path + os.sep + 'oh_encoder.json')
        oh_encoders_json_file = json.load(oh_encoders_file)
        oh_encoders_file.close()

    # TODO : Display model based on dep var type

    X = df_model.drop([dependent_variable], axis=1)
    y = df_model[dependent_variable]

    # if utils.multiclass.type_of_target(y) == 'continuous':
    #     y = utils.multiclass.type_of_target(y.astype('int'))
    # print(utils.multiclass.type_of_target(y))
    # lab_enc = preprocessing.LabelEncoder()
    # encoded = lab_enc.fit_transform(y)
    # print(utils.multiclass.type_of_target(encoded))

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size_ratio, random_state=77, shuffle=True)
    p_X_train = X_train.copy()
    p_X_test = X_test.copy()

    if request.method == 'POST':
        sc_X = StandardScaler()
        model_name = request.POST.get('model_name')
        chosen_model_name = model_name
        train_model_button = request.POST.get('train_model_button')
        # evaluation_button = request.POST.get('evaluation')
        save_model_button = request.POST.get('save_model_button')

        if train_model_button:
            model_details = {}
            if model_name in ['(AutoML) Regression', '(AutoML) Classification']:
                if model_name.split(" ")[-1] == 'Classification':
                    X_train = sc_X.fit_transform(X_train)
                    X_test = sc_X.transform(X_test)
                    classifier = True

                automl_model_name, model = get_automl_model((model_name.split(" ")[-1]).lower(), X_train, y_train)
                model_details['model_name'] = automl_model_name

            else:
                if model_name == 'Linear Regression':
                    model = get_linear_regression_model(X_train, y_train)
                elif utils.multiclass.type_of_target(y) == 'continuous':
                    messages.info(request, "Your Target Variable is 'Continuous' type, Please Use Regression Models.")
                    context = {'model_name_list': all_ml_models}
                    return render(request, 'model_selection.html', context)
                else:
                    p_X_train = X_train.copy()
                    p_X_test = X_test.copy()
                    X_train = sc_X.fit_transform(X_train)
                    X_test = sc_X.transform(X_test)
                    if model_name == 'Logistic Regression':
                        model = get_logistic_regression_model(X_train, y_train)
                    elif model_name == 'Decision Tree Classifier':
                        model = get_decision_tree_classifier_model(X_train, y_train)
                    elif model_name == 'Random Forest Classifier':
                        model = get_random_forest_classifier_model(X_train, y_train)
                    elif model_name == 'GaussianNB':
                        model = get_gaussian_nb_model(X_train, y_train)
                    elif model_name == 'SGDClassifier':
                        model = get_sgd_classifier_model(X_train, y_train)
                    else:
                        model = get_kneighbors_classifier_model(X_train, y_train)
                    classifier = True

                model_details['model_name'] = model_name

            model_details['model_type'] = model_name
            model_details['predictions'] = model.predict(X_test)
            if classifier:
                X_train = p_X_train
                X_test = p_X_test

            actual_pred_df = X_test.copy()
            actual_pred_df[dependent_variable] = y_test
            actual_pred_df[dependent_variable + ' (Predictions)'] = model_details['predictions']
            # actual_pred_df = actual_pred_df.to_html(
            #     classes="table table-bordered table-striped table-hover custom-table",
            #     index=False)  # , table_id='myTable')

            model_name = model_details['model_name']
            model_eva_type = model_details['model_type']
            y_pred = model_details['predictions']

            if model_eva_type in ['(AutoML) Regression', 'Linear Regression']:
                folder_ = media_path + os.sep + user + os.sep + 'regression_graphs'
                check_dir_exists(folder_)
                # png_file_name_ = folder_ + os.sep + "true_vs_predictions.png"
                mae = metrics.mean_absolute_error(y_test, y_pred)
                mse = metrics.mean_squared_error(y_test, y_pred)
                rmse = np.sqrt(metrics.mean_squared_error(y_test, y_pred))

                my_data = [['Model', model_name], ['Mean Absolute Error', mae],
                           ['Mean Squared Error', mse], ['Root Mean Squared Error', rmse]]
            else:
                unique_classes = y_test.nunique()
                if unique_classes == 2:
                    accuracy = '%.2f' % (metrics.accuracy_score(y_test, y_pred) * 100) + ' %'
                    recall = '%.2f' % (metrics.recall_score(y_test, y_pred) * 100) + ' %'
                    f1 = '%.2f' % (metrics.f1_score(y_test, y_pred) * 100) + ' %'
                    precision = '%.2f' % (metrics.precision_score(y_test, y_pred) * 100) + ' %'
                elif 15 > unique_classes > 2:
                    accuracy = '%.2f' % (metrics.accuracy_score(y_test, y_pred) * 100) + ' %'
                    recall = '%.2f' % (metrics.recall_score(y_test, y_pred, average='weighted') * 100) + ' %'
                    f1 = '%.2f' % (metrics.f1_score(y_test, y_pred, average='weighted') * 100) + ' %'
                    precision = '%.2f' % (metrics.precision_score(y_test, y_pred, average='weighted') * 100) + ' %'
                else:
                    messages.info(request, 'For Regression problem, use only Regression model')
                    return redirect('/model_selection/')

                my_data = [['Model', model_name], ['Accuracy Score', accuracy],
                           ['Recall Score', recall], ['F1 score', f1], ['Precision', precision]]

            df_ev = pd.DataFrame(my_data, columns=['Metrics', 'Values'])
            df_ev_to_html = df_ev.to_html(classes="table table-bordered table-striped table-hover custom-table",
                                          index=False)

            with open(media_path + os.sep + str(user) + os.sep + 'documents' + os.sep + 'model', 'wb') as files:
                pickle.dump(model, files)

            with open(media_path + os.sep + str(user) + os.sep + 'documents' + os.sep + "model_details.json",
                      "w") as outfile:
                json.dump(model_details, outfile, cls=NumpyArrayEncoder)

            all_ml_models.remove(chosen_model_name)
            all_ml_models.insert(0, chosen_model_name)

            messages.success(request, f'Model "{str(model_name)}" has been trained successfully!')

            if not classifier:
                actual_pred_df[dependent_variable + ' (Predictions)'] = actual_pred_df[
                    dependent_variable + ' (Predictions)'].round(2)
                differences = np.abs(y_test.values - y_pred).round(2)
                actual_pred_df['Differences'] = differences
            elif dependent_variable in oh_encoders_json_file.keys():
                dependent_variable_mapping = oh_encoders_json_file.get(dependent_variable)
                reversed_mapping = {v: k for k, v in dependent_variable_mapping.items()}
                actual_pred_df[dependent_variable + ' (Predictions)'].replace(reversed_mapping, inplace=True)

            if oh_encoders_json_file:
                columns_to_delete = []
                for column, column_mapping in oh_encoders_json_file.items():
                    if column in actual_pred_df.columns:
                        reversed_mapping = {v: k for k, v in column_mapping.items()}
                        actual_pred_df[column].replace(reversed_mapping, inplace=True)
                    else:
                        columns_to_delete.append(column)

                for column in columns_to_delete:
                    del oh_encoders_json_file[column]

            actual_pred_df_json = actual_pred_df.values.tolist()
            actual_pred_df_columns = actual_pred_df.columns.astype(str).to_list()
            actual_pred_df = actual_pred_df.to_html(
                classes="table table-bordered table-striped table-hover custom-table",
                index=False, table_id="predictionTable"
            )

            context = {'actual_pred_df': actual_pred_df, 'model_name_list': all_ml_models,
                       'df_ev_to_html': df_ev_to_html, 'actual_pred_df_json': actual_pred_df_json,
                       'actual_pred_df_columns': actual_pred_df_columns}

            return render(request, 'model_selection.html', context)

        elif save_model_button:
            X.to_csv(docs_path + os.sep + 'X.csv')
            y.to_csv(docs_path + os.sep + 'y.csv')
            X_train.to_csv(docs_path + os.sep + 'X_train.csv')
            y_train.to_csv(docs_path + os.sep + 'y_train.csv')
            X_test.to_csv(docs_path + os.sep + 'X_test.csv')
            y_test.to_csv(docs_path + os.sep + 'y_test.csv')

            # # TODO: check model details json, model pickle file and load it in next function
            # # model_details = {'X': X, 'y': y, 'X_train': X_train, 'y_train': y_train, 'X_test': X_test, 'y_test': y_test}

            return redirect('/save_model/')

    context = {'model_name_list': all_ml_models}
    return render(request, 'model_selection.html', context)  # except:  #     return redirect('/eda/')


def model_evaluation(request):
    if 'guest_session_id' not in request.session and not request.user.is_authenticated:
        return redirect('/signin/')

    user = str(request.user.id) if request.user.id else request.session['guest_session_id']
    docs_path = media_path + os.sep + user + os.sep + 'documents'
    if not os.path.isfile(docs_path + os.sep + 'model_details.json'):
        return redirect('/upload/')
    file = open(docs_path + os.sep + 'model_details.json')
    json_file = json.load(file)
    file.close()
    model_name = json_file['model_name']
    y_test = pd.read_csv(docs_path + os.sep + 'y_test.csv')
    y_test.drop(columns=y_test.columns[0], axis=1, inplace=True)
    y_pred = np.asarray(json_file['predictions'])
    model_eva_type = json_file['model_type']

    if model_eva_type in ['(AutoML) Regression', 'Linear Regression']:
        folder_ = media_path + os.sep + user + os.sep + 'regression_graphs'
        check_dir_exists(folder_)
        png_file_name_ = folder_ + os.sep + "true_vs_predictions.png"
        mae = metrics.mean_absolute_error(y_test, y_pred)
        mse = metrics.mean_squared_error(y_test, y_pred)
        rmse = np.sqrt(metrics.mean_squared_error(y_test, y_pred))
        # model_score = '%.2f' % (model.score(X_test, y_test) * 100) + ' %'
        # my_data = [['Model', model_name], ['Mean Absolute Error', mae], ['Mean Squared Error', mse],
        #            ['Root Mean Squared Error', rmse], ['Model Score', model_score]]

        my_data = [['Model', model_name], ['Mean Absolute Error', mae],
                   ['Mean Squared Error', mse], ['Root Mean Squared Error', rmse]]

    else:
        # print(model_name)
        # cm = confusion_matrix(y_test, y_pred)
        # print("TN", cm[0][0], "FP", cm[0][1])
        # print("FN", cm[1][0], "TP", cm[1][1])
        # class_report = metrics.classification_report(y_test, y_pred)
        # print("class_report: ", class_report)

        # if _check_targets(y_test, y_pred)[0] == 'multiclass':
        #     average = 'multiclass'
        # else:
        #     average = 'binary'

        # accuracy = '%.2f' % (metrics.accuracy_score(y_test, y_pred) * 100) + ' %'
        # recall = '%.2f' % (metrics.recall_score(y_test, y_pred, average=average) * 100) + ' %'
        # f1 = '%.2f' % (metrics.f1_score(y_test, y_pred, average=average) * 100) + ' %'
        # precision = '%.2f' % (metrics.precision_score(y_test, y_pred, average=average) * 100) + ' %'

        try:
            accuracy = '%.2f' % (metrics.accuracy_score(y_test, y_pred) * 100) + ' %'
            recall = '%.2f' % (metrics.recall_score(y_test, y_pred) * 100) + ' %'
            f1 = '%.2f' % (metrics.f1_score(y_test, y_pred) * 100) + ' %'
            precision = '%.2f' % (metrics.precision_score(y_test, y_pred) * 100) + ' %'

        except (Exception,):
            messages.info(request, 'For Regression problem, use only Regression model')
            return redirect('/model_selection/')
            # return render(request, 'model_evaluation.html')

        my_data = [['Model', model_name], ['Accuracy Score', accuracy],
                   ['Recall Score', recall], ['F1 score', f1], ['Precision', precision]]

        png_file_name_ = None

    df_ev = pd.DataFrame(my_data, columns=['Metrics', 'Values'])
    df_to_html = df_ev.to_html(classes="table table-bordered table-striped table-hover custom-table", index=False)

    context = {'model_name': model_name, 'df': df_to_html, 'fig': png_file_name_, }
    return render(request, 'model_evaluation.html', context)


def save_model(request):
    if 'guest_session_id' in request.session and not request.user.is_authenticated:
        messages.warning(request, 'Create an account to save the model.')
        return redirect('/model_selection/')
    elif 'guest_session_id' not in request.session and not request.user.is_authenticated:
        return redirect('/signin/')

    user_id = request.user.id
    user = User.objects.get(id=user_id)
    docs_path = media_path + os.sep + str(user_id) + os.sep + 'documents'
    graphs_path = media_path + os.sep + str(user_id) + os.sep + 'graphs'
    if user:
        if not os.path.isfile(docs_path + os.sep + 'model_details.json'):
            return redirect('/upload/')
        file = open(docs_path + os.sep + 'model_details.json')
        json_file = json.load(file)
        file.close()
        with open(docs_path + os.sep + 'model', 'rb') as f:
            model = pickle.load(f)
        model_name = json_file['model_name']
        used_model_type = json_file['model_type']
        file.close()
        X = pd.read_csv(docs_path + os.sep + 'X.csv')
        X.drop(columns=X.columns[0], axis=1, inplace=True)
        y = pd.read_csv(docs_path + os.sep + 'y.csv')
        y.drop(columns=y.columns[0], axis=1, inplace=True)
        X_cols = X.columns.tolist()
        if request.method == 'POST':
            project_name = request.POST.get('project_name')
            pickle_file = pickle.dumps(model)

            if os.path.exists(docs_path + os.sep + 'oh_encoder.json'):
                oh_encoder = json.load(open(docs_path + os.sep + 'oh_encoder.json'))
            else:
                oh_encoder = None

            # ============ Saving document path with user id ============ #
            file_path = media_path + os.sep + str(user_id) + os.sep + 'documents' + os.sep + 'input_files'
            list_of_files = glob.glob(file_path + os.sep + '*')
            file_name = max(list_of_files, key=os.path.getmtime)
            doc_instance = Document(user_id=user.id, document=file_name)
            doc_instance.save()

            X_json = X.to_json(orient='records')
            data = TrainedModels(user_id=user.id, document=doc_instance, project_name=project_name,
                                 model_file=pickle_file, column_names=X_cols, model_name=model_name,
                                 model_type=used_model_type,
                                 oh_encoders=oh_encoder, independent_variable=X_json,
                                 dependent_variable=y.columns.tolist()[0])
            data.save()

            # ============ Clearing memory - Comment to keep the files ============
            # os.remove(os.path.join(docs_path, 'oh_encoder.json'))
            shutil.rmtree(docs_path)
            shutil.rmtree(graphs_path)

            messages.success(request, 'Your Project has been saved successfully !')

            return redirect('/profile_data/')
        return render(request, 'save_model.html')
    else:
        return redirect("/signin/")


@decorators.login_required
def profile_data(request):
    user = str(request.user.id)
    if user:
        if request.method == 'POST':
            button_id = request.POST.get('test_model_button')
            if '_delete' in button_id:
                model_instance = get_object_or_404(TrainedModels, id=str(button_id).split("_")[0])
                project_name = model_instance.project_name
                document = model_instance.document
                document.delete()
                model_instance.delete()
                messages.success(request, f'Project "{project_name}" Deleted Successfully!')
                return redirect('/profile_data/')
            return redirect(f'/model_testing/{int(button_id)}')
        document = Document.objects.filter(user_id=user)
        if document:
            model_data = TrainedModels.objects.filter(
                document_id__in=document.values_list('id', flat=True)).values_list('project_name', flat=True)
            docs_name_list = [str(doc).split("/")[-1] for doc in document]
            projects_name_list = [str(md) for md in model_data]
            model_id = list(model_data.values_list('id', flat=True))
            if not docs_name_list or not projects_name_list or not model_id:
                context = {'document_project_name': None, }
            else:
                context = {'document_project_name': zip(docs_name_list, projects_name_list, model_id), }
        else:
            context = {'document_project_name': None, }
        return render(request, 'profile_data.html', context)
    else:
        return redirect('/signin/')


@decorators.login_required
def model_testing(request, button_id):
    user = request.user
    user_id = user.id
    if user_id:
        model_data = TrainedModels.objects.filter(user=user_id, id=button_id).values()
        if not model_data:
            return redirect('/profile_data/')
        df_test, y = None, None
        project_name = model_data[0]['project_name']
        model_name = model_data[0]['model_name']
        col_names = ast.literal_eval(model_data[0]['column_names'])
        predict = ["" for _ in col_names]
        if request.method == 'POST':
            if 'predict_file' in request.POST:
                file = request.FILES.get('myFile')
                try:
                    df = pd.read_csv(file)
                except Exception as e:
                    messages.error(request, f'Error reading CSV file: {e}')
                    context = {'model_name': model_name, 'col': zip(col_names, predict),
                               'project_name': project_name}
                    return render(request, 'model_testing.html', context)

                missing_columns = set(col_names) - set(df.columns)
                if missing_columns:
                    messages.error(request,
                                   f'The following columns are missing in the uploaded file: {", ".join(missing_columns)}')
                    context = {'model_name': model_name, 'col': zip(col_names, predict),
                               'project_name': project_name}
                    return render(request, 'model_testing.html', context)

                sc_X = StandardScaler()
                model_file = pickle.loads(model_data[0]['model_file'])
                saved_model_type = model_data[0]['model_type']
                one_hot_decoder = model_data[0]['oh_encoders']
                X = ast.literal_eval(model_data[0]['independent_variable'])
                y = model_data[0]['dependent_variable']

                df_selected = df[col_names]
                all_predictions = []
                for index, row in df_selected.iterrows():
                    wrong_data = False
                    to_be_predicted = []
                    predict = list(row)
                    for column, value in zip(col_names, predict):
                        if one_hot_decoder and column in one_hot_decoder.keys():
                            if str(value).lower() not in one_hot_decoder[column]:
                                wrong_data = True
                                break
                            val = one_hot_decoder[column][value.lower()]
                            if isinstance(val, int):
                                to_be_predicted.append(int(val))
                            else:
                                to_be_predicted.append(float(val))
                        else:
                            try:
                                if isinstance(value, int):
                                    to_be_predicted.append(int(value))
                                else:
                                    to_be_predicted.append(float(value))
                            except (Exception,):
                                wrong_data = True
                                break

                    if wrong_data:
                        all_predictions.append("Improper Inputs!")
                    else:
                        to_be_predicted = [to_be_predicted]
                        if saved_model_type not in ['Linear Regression']:
                            sc_X.fit(pd.DataFrame(X))
                            to_be_predicted = sc_X.transform(pd.DataFrame(to_be_predicted, columns=col_names))
                        test_data = str(model_file.predict(to_be_predicted)[0])
                        all_predictions.append(test_data)
                df_selected[y + "_(Predictions)"] = all_predictions
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = 'attachment; filename="predictions.csv"'
                df_selected.to_csv(path_or_buf=response, index=False)
                # messages.success(request, "File Downloaded Successfully!")
                return response
            else:
                predict = request.POST.getlist('inputs')
                sc_X = StandardScaler()
                model_file = model_data[0]['model_file']
                saved_model_type = model_data[0]['model_type']
                one_hot_decoder = model_data[0]['oh_encoders']
                X = ast.literal_eval(model_data[0]['independent_variable'])
                y = model_data[0]['dependent_variable']
                to_be_predicted = []
                for column, value in zip(col_names, predict):
                    if one_hot_decoder and column in one_hot_decoder.keys():
                        if value.lower() not in one_hot_decoder[column]:
                            messages.error(request, f'Improper value for column: "{column}", '
                                                    f'choose one from {list(one_hot_decoder[column].keys())}')
                            context = {'model_name': model_name, 'col': zip(col_names, predict),
                                       'project_name': project_name}
                            return render(request, 'model_testing.html', context)
                        val = one_hot_decoder[column][value.lower()]
                        if isinstance(val, int):
                            to_be_predicted.append(int(val))
                        else:
                            to_be_predicted.append(float(val))
                    else:
                        try:
                            if isinstance(value, int):
                                to_be_predicted.append(int(value))
                            else:
                                to_be_predicted.append(float(value))
                        except (Exception,):
                            messages.error(request, f'Improper value for column: "{column}"')
                            context = {'model_name': model_name, 'col': zip(col_names, predict),
                                       'project_name': project_name}
                            return render(request, 'model_testing.html', context)

                model_file = pickle.loads(model_file)
                to_be_predicted = [to_be_predicted]
                if saved_model_type not in ['Linear Regression']:
                    sc_X.fit(pd.DataFrame(X))
                    to_be_predicted = sc_X.transform(pd.DataFrame(to_be_predicted, columns=col_names))
                test_data = [[y, str(model_file.predict(to_be_predicted)[0])]]
                df_test = pd.DataFrame(test_data, columns=['Target Variable', 'Prediction'])
                df_test = df_test.to_html(classes="table table-bordered table-striped table-hover custom-table",
                                          index=False)
        context = {'model_name': model_name, 'predictions': df_test, 'col': zip(col_names, predict),
                   'project_name': project_name}
        return render(request, 'model_testing.html', context)
    else:
        return redirect('/signin/')


@csrf_exempt
def model_test_api(request):
    try:
        if request.method == 'POST':
            username = request.POST.get('username')
            model_name = request.POST.get('model_name')
            predict = request.POST.getlist('inputs')

            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                raise Exception(f'User "{username}" does not exist')
            model_data = user.trainedmodels_set.filter(model_name=model_name).values()

            if not model_data:
                raise Exception(f'Model "{model_name}" not found')
            y = None
            model_name = model_data[0]['model_name']
            col_names = ast.literal_eval(model_data[0]['column_names'])
            predict = ["" for _ in col_names]
            sc_X = StandardScaler()
            model_file = model_data[0]['model_file']
            saved_model_type = model_data[0]['model_type']
            one_hot_decoder = model_data[0]['oh_encoders']
            X = ast.literal_eval(model_data[0]['independent_variable'])
            y = model_data[0]['dependent_variable']
            predict = request.POST.getlist('inputs')
            to_be_predicted = []
            for column, value in zip(col_names, predict):
                if one_hot_decoder and column in one_hot_decoder.keys():
                    if value.lower() not in one_hot_decoder[column]:
                        raise Exception(
                            f'Improper value for column: "{column}", choose one from {list(one_hot_decoder[column].keys())}')
                    val = one_hot_decoder[column][value.lower()]
                    if isinstance(val, int):
                        to_be_predicted.append(int(val))
                    else:
                        to_be_predicted.append(float(val))
                else:
                    try:
                        if isinstance(value, int):
                            to_be_predicted.append(int(value))
                        else:
                            to_be_predicted.append(float(value))
                    except (Exception,):
                        raise Exception(f'Improper value for column: "{column}"')

            model_file = pickle.loads(model_file)
            to_be_predicted = [to_be_predicted]
            if saved_model_type not in ['Linear Regression']:
                sc_X.fit(pd.DataFrame(X))
                to_be_predicted = sc_X.transform(pd.DataFrame(to_be_predicted, columns=col_names))

            response_data = {
                'Target Variable': y,
                'Prediction': str(model_file.predict(to_be_predicted)[0])
            }
            return JsonResponse(response_data, status=200)

        raise Exception("Invalid Request")

    except Exception as e:
        error_response = {'error': str(e)}
        return JsonResponse(error_response, status=400)


@csrf_exempt
def delete_model_api(request):
    try:
        if request.method == 'POST':
            username = request.POST.get('username')
            model_name = request.POST.get('model_name')
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                raise Exception(f'User "{username}" does not exist')
            model_instance = user.trainedmodels_set.filter(model_name=model_name).values()
            if not model_instance:
                raise Exception(f'Model "{model_name}" not found!')
            project_name = model_instance[0]['project_name']
            document = model_instance[0]['document']
            document.delete()
            model_instance.delete()

            response_data = {
                'message': f'Project "{project_name}" Deleted Successfully!'
            }
            return JsonResponse(response_data)
        raise Exception('Invalid Request')

    except Exception as e:
        error_response = {'error': str(e)}
        return JsonResponse(error_response, status=400)
