// Administrator backup downloads and password-first recovery preparation.
document.addEventListener('DOMContentLoaded', () => {
  const dialog = document.getElementById('restoreDialog');
  if (!dialog) return;
  const form = document.getElementById('restoreForm');
  const passwordStep = document.getElementById('restorePasswordStep');
  const fileStep = document.getElementById('restoreFileStep');
  const submit = document.getElementById('restoreSubmit');
  const result = document.getElementById('restoreResult');
  const csrf = form.querySelector('[name="csrfmiddlewaretoken"]').value;
  let token = '';
  let busy = false;

  const clearErrors = () => {
    form.querySelectorAll('.inline-form-error').forEach(node => { node.textContent = ''; });
    form.querySelectorAll('[aria-invalid]').forEach(node => node.removeAttribute('aria-invalid'));
  };
  const showError = (name, message) => {
    const field = form.elements.namedItem(name);
    const error = document.getElementById(`${name}_error`);
    if (error) error.textContent = message;
    if (field) { field.setAttribute('aria-invalid', 'true'); field.focus(); }
  };
  const reset = () => {
    token = '';
    form.reset();
    clearErrors();
    passwordStep.hidden = false;
    fileStep.hidden = true;
    result.textContent = '';
    submit.hidden = false;
    submit.textContent = 'Verify password';
  };
  document.getElementById('openRestore').addEventListener('click', () => {
    reset();
    dialog.showModal();
    form.elements.restore_password.focus();
  });
  document.getElementById('closeRestore').addEventListener('click', () => {
    if (!busy) dialog.close();
  });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    clearErrors();
    result.textContent = '';
    if (!token && !form.elements.restore_password.value) {
      showError('restore_password', 'Enter your administrator password.');
      return;
    }
    if (token && !form.elements.restore_archive.files.length) {
      showError('restore_archive', 'Choose an FMIS encrypted backup file (.fmisbak).');
      return;
    }
    const body = new FormData();
    body.set('restore_action', token ? 'prepare' : 'unlock');
    if (token) {
      body.set('restore_token', token);
      body.set('restore_archive', form.elements.restore_archive.files[0]);
    } else body.set('restore_password', form.elements.restore_password.value);
    busy = true;
    submit.disabled = true;
    try {
      const response = await fetch(form.action, {method: 'POST', headers: {'X-CSRFToken': csrf, Accept: 'application/json'}, body});
      if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('Your session may have expired. Reload the page and try again.');
      const data = await response.json();
      if (!response.ok || !data.ok) {
        if (data.errors?.restore_password) {
          token = '';
          passwordStep.hidden = false;
          fileStep.hidden = true;
          submit.textContent = 'Verify password';
        }
        Object.entries(data.errors || {}).forEach(([name, message]) => showError(name, message));
        return;
      }
      form.elements.restore_password.value = '';
      if (data.token) {
        token = data.token;
        passwordStep.hidden = true;
        fileStep.hidden = false;
        submit.textContent = 'Prepare recovery package';
        form.elements.restore_archive.focus();
      } else {
        token = '';
        fileStep.hidden = true;
        submit.hidden = true;
        result.textContent = data.message;
      }
    } catch (error) {
      result.textContent = error.message || 'The request failed. Please try again.';
    } finally {
      busy = false;
      submit.disabled = false;
    }
  });

  const backup = document.getElementById('downloadBackup');
  backup.addEventListener('click', async () => {
    if (backup.disabled) return;
    backup.disabled = true;
    const status = document.getElementById('backupResult');
    status.textContent = 'Creating and verifying encrypted backup…';
    try {
      const response = await fetch(backup.dataset.url, {method: 'POST', headers: {'X-CSRFToken': csrf}});
      if (!response.ok || !response.headers.get('Content-Disposition')?.includes('attachment')) throw new Error('Backup could not be completed. Check backup configuration and try again.');
      const blob = await response.blob();
      const filename = response.headers.get('Content-Disposition').match(/filename="([^"]+)"/)?.[1] || 'fmis-backup.fmisbak';
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      status.textContent = `Backup verified and saved in encrypted ${response.headers.get('X-Backup-Storage') === 'offsite' ? 'server and off-site' : 'server'} storage. Download started: ${filename}.`;
    } catch (error) {
      status.textContent = error.message;
    } finally {
      backup.disabled = false;
    }
  });
});
