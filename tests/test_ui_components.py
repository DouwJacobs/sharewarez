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
