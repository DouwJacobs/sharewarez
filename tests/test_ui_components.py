from jinja2 import Environment, FileSystemLoader
from wtforms import Form, SelectField
from wtforms.validators import DataRequired


class ExampleForm(Form):
    theme = SelectField(
        'Theme',
        choices=[('light', 'Light')],
        validators=[DataRequired()],
    )


def _render_form_field(form: ExampleForm) -> str:
    environment = Environment(
        loader=FileSystemLoader('sharewarez/templates'),
        autoescape=True,
    )
    template = environment.from_string(
        "{% from 'partials/ui_components.html' import form_field %}"
        "{{ form_field(form.theme, 'form-select', 'Choose a theme.') }}"
    )
    return template.render(form=form)


def test_page_header_accepts_route_hooks_and_actions():
    environment = Environment(
        loader=FileSystemLoader('sharewarez/templates'),
        autoescape=True,
    )
    template = environment.from_string(
        "{% from 'partials/ui_components.html' import page_header %}"
        "{% call page_header('Activity', 'Recent events.', 'Account', "
        "title_id='activity-title', class_name='activity-header', "
        "eyebrow_class='activity-eyebrow') %}"
        "<a href='/inbox'>Inbox</a>"
        "{% endcall %}"
    )

    rendered = template.render()

    assert 'app-page-header ui-page-header activity-header' in rendered
    assert 'ui-page-eyebrow activity-eyebrow' in rendered
    assert 'id="activity-title"' in rendered
    assert '<div class="app-page-actions"><a href=' in rendered


def test_admin_page_header_accepts_route_hooks_and_actions():
    environment = Environment(
        loader=FileSystemLoader('sharewarez/templates'),
        autoescape=True,
    )
    template = environment.from_string(
        "{% from 'partials/ui_components.html' import admin_page_header %}"
        "{% call admin_page_header('Email', 'Manage messages.', 'Communication', "
        "'fa-envelope', title_id='email-title', class_name='email-header', "
        "eyebrow_class='email-eyebrow', actions_class='email-actions') %}"
        "<a href='/smtp'>SMTP</a>"
        "{% endcall %}"
    )

    rendered = template.render()

    assert 'admin-page-header email-header' in rendered
    assert 'admin-page-eyebrow email-eyebrow' in rendered
    assert 'id="email-title"' in rendered
    assert 'admin-page-actions email-actions' in rendered


def test_form_field_links_help_text_to_valid_control():
    form = ExampleForm(data={'theme': 'light'})

    assert form.validate()
    rendered = _render_form_field(form)

    assert 'aria-describedby="theme-help"' in rendered
    assert 'aria-invalid="false"' in rendered
    assert 'is-invalid' not in rendered


def test_form_field_exposes_validation_errors_accessibly():
    form = ExampleForm(data={'theme': ''})

    assert not form.validate()
    rendered = _render_form_field(form)

    assert 'class="form-select is-invalid"' in rendered
    assert 'aria-describedby="theme-help theme-errors"' in rendered
    assert 'aria-invalid="true"' in rendered
    assert 'id="theme-errors"' in rendered
    assert 'role="alert"' in rendered
    assert 'This field is required.' in rendered
