<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, auth } from '../api'
import RichTextEditor from '../components/RichTextEditor.vue'

const campaigns = ref([])
const clients = ref([])
const groups = ref([])
const sharedSenders = ref([])
const templates = ref([])
const editingId = ref(null)
const newFiles = ref([])
const previewOpen = ref(false)
const error = ref('')
const message = ref('')
const sending = ref(false)
const personalizationVariables = [
  { value: '{{FirstName}}', label: 'Ім’я', description: 'Ім’я клієнта або перше слово з поля «Контактна особа»' },
  { value: '{{CompanyName}}', label: 'Компанія клієнта', description: 'Назва компанії з анкети клієнта' },
  { value: '{{Company}}', label: 'Наша компанія', description: 'Назва компанії-відправника з email-налаштувань' },
]
const emptyForm = () => ({
  message_type: 'service', sender_type: 'personal', shared_sender_id: null,
  subject: '', html_body: '<p>Вітаємо, {{FirstName}}!</p>', text_body: '',
  target_mode: 'selected', client_ids: [], client_group_ids: [],
})
const form = reactive(emptyForm())
const user = computed(() => auth.user())
const activeClients = computed(() => clients.value.filter(item => item.status !== 'archived'))
const previewDocument = computed(() => `<!doctype html><html><head><meta charset="utf-8"><style>body{font:16px Arial,sans-serif;padding:24px;color:#17201c;line-height:1.5}</style></head><body>${form.html_body || ''}</body></html>`)

const statusLabels = {
  draft: 'Чернетка', queued: 'У черзі', processing: 'Надсилається', completed: 'Завершено',
  partial_failed: 'Є помилки', failed: 'Помилка',
}

async function load() {
  error.value = ''
  try {
    const result = await Promise.all([
      api('/email-campaigns/'), api('/clients/'), api('/client-groups/'),
      api('/shared-senders/'), api('/email-templates/'),
    ])
    ;[campaigns.value, clients.value, groups.value, sharedSenders.value, templates.value] = result
  } catch (e) { error.value = e.message }
}

function applyTemplate() {
  const id = Number(document.querySelector('#campaign-template')?.value || 0)
  const template = templates.value.find(item => item.id === id)
  if (!template) return
  Object.assign(form, {
    message_type: template.message_type,
    subject: template.subject,
    html_body: template.html_body,
    text_body: template.text_body,
  })
}

function insertSubjectVariable(event) {
  const marker = event.target.value
  if (marker) form.subject += marker
  event.target.value = ''
}

function payload() {
  const data = {
    message_type: form.message_type,
    sender_type: form.sender_type,
    subject: form.subject,
    html_body: form.html_body,
    text_body: form.text_body,
    client_ids: [], client_group_ids: [], include_all_accessible: false,
  }
  if (form.sender_type === 'shared') data.shared_sender_id = form.shared_sender_id
  if (form.target_mode === 'all') data.include_all_accessible = true
  if (form.target_mode === 'selected') data.client_ids = form.client_ids
  if (form.target_mode === 'groups') data.client_group_ids = form.client_group_ids
  return data
}

async function uploadAttachments(campaignId) {
  for (const file of newFiles.value) {
    const body = new FormData()
    body.append('file', file)
    await api(`/email-campaigns/${campaignId}/attachment/`, { method: 'POST', body })
  }
}

async function saveCampaign(queueAfter = false) {
  error.value = ''; message.value = ''; sending.value = true
  try {
    const path = editingId.value ? `/email-campaigns/${editingId.value}/` : '/email-campaigns/'
    const campaign = await api(path, {
      method: editingId.value ? 'PATCH' : 'POST', body: JSON.stringify(payload()),
    })
    await uploadAttachments(campaign.id)
    if (queueAfter) {
      await api(`/email-campaigns/${campaign.id}/queue/`, { method: 'POST', body: '{}' })
      message.value = 'Розсилку поставлено в чергу.'
    } else message.value = 'Чернетку збережено.'
    resetForm(); await load()
  } catch (e) { error.value = e.message }
  finally { sending.value = false }
}

function editDraft(item) {
  editingId.value = item.id
  Object.assign(form, {
    message_type: item.message_type,
    sender_type: item.sender_type,
    shared_sender_id: item.shared_sender?.id || null,
    subject: item.subject,
    html_body: item.html_body,
    text_body: item.text_body,
    target_mode: 'selected',
    client_ids: item.recipients.map(recipient => recipient.client),
    client_group_ids: [],
  })
  newFiles.value = []
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function resetForm() {
  editingId.value = null
  Object.assign(form, emptyForm())
  newFiles.value = []
  previewOpen.value = false
}

async function deleteDraft(item) {
  if (!window.confirm(`Видалити чернетку «${item.subject}»?`)) return
  try { await api(`/email-campaigns/${item.id}/`, { method: 'DELETE' }); await load() }
  catch (e) { error.value = e.message }
}

async function savePersonalTemplate() {
  const name = window.prompt('Назва особистого шаблону')
  if (!name) return
  try {
    await api('/email-templates/', {
      method: 'POST',
      body: JSON.stringify({ name, scope: 'personal', message_type: form.message_type, subject: form.subject, html_body: form.html_body, text_body: form.text_body }),
    })
    message.value = 'Особистий шаблон збережено.'; await load()
  } catch (e) { error.value = e.message }
}

async function deletePersonalTemplate(item) {
  if (item.scope !== 'personal' || !window.confirm(`Видалити шаблон «${item.name}»?`)) return
  try { await api(`/email-templates/${item.id}/`, { method: 'DELETE' }); await load() }
  catch (e) { error.value = e.message }
}

onMounted(load)
</script>

<template>
  <header class="page-header"><div><p class="eyebrow">EMAIL-КАМПАНІЇ</p><h1>Масові розсилки</h1><p>До 100 унікальних адрес із числа доступних вам клієнтів.</p></div></header>
  <p v-if="message" class="success">{{ message }}</p>

  <section class="panel campaign-composer">
    <div class="section-heading"><div><h2>{{ editingId ? 'Редагування чернетки' : 'Новий лист' }}</h2><p>Персональні змінні перевіряються для кожного одержувача перед відправкою.</p></div><button v-if="editingId" class="secondary" @click="resetForm">Нова розсилка</button></div>
    <div class="grid two">
      <label>Шаблон<select id="campaign-template" @change="applyTemplate"><option value="">Без шаблону</option><option v-for="item in templates" :key="item.id" :value="item.id">{{ item.scope === 'company' ? 'Спільний' : 'Мій' }} · {{ item.name }}</option></select></label>
      <label>Тип листа<select v-model="form.message_type"><option value="service">Службовий — незалежно від рекламної згоди</option><option value="marketing">Рекламний — лише за згодою клієнта</option></select></label>
      <label>Відправник<select v-model="form.sender_type"><option value="personal">{{ user?.first_name || user?.username }} &lt;{{ user?.email }}&gt;</option><option v-if="sharedSenders.length" value="shared">Загальна адреса</option></select></label>
      <label v-if="form.sender_type === 'shared'">Загальна адреса<select v-model="form.shared_sender_id" required><option :value="null">Оберіть адресу</option><option v-for="sender in sharedSenders" :key="sender.id" :value="sender.id">{{ sender.name }} &lt;{{ sender.email }}&gt;</option></select></label>
      <label class="span-two">Тема<input v-model="form.subject" required maxlength="255" /><select aria-label="Додати змінну до теми" @change="insertSubjectVariable"><option value="">+ Додати змінну</option><option v-for="item in personalizationVariables" :key="item.value" :value="item.value">{{ item.label }} — {{ item.value }}</option></select></label>
      <label class="span-two">Лист<RichTextEditor v-model="form.html_body" :variables="personalizationVariables" /></label>
      <label class="span-two">Текстова версія<textarea v-model="form.text_body" rows="4" placeholder="Необов’язково — CRM створить її з оформленого листа" /></label>
      <div class="span-two"><small v-for="item in personalizationVariables" :key="item.value"><code>{{ item.value }}</code> — {{ item.description }}<br /></small></div>
    </div>

    <fieldset class="target-picker"><legend>Одержувачі</legend>
      <div class="segmented"><label><input v-model="form.target_mode" type="radio" value="selected" /> Вибрані клієнти</label><label><input v-model="form.target_mode" type="radio" value="groups" /> Групи</label><label><input v-model="form.target_mode" type="radio" value="all" /> Усі доступні</label></div>
      <div v-if="form.target_mode === 'selected'" class="recipient-grid"><label v-for="client in activeClients" :key="client.id" class="recipient-option"><input v-model="form.client_ids" type="checkbox" :value="client.id" /><span><strong>{{ client.display_name }}</strong><small>{{ client.email }}</small></span><span v-if="client.marketing_email_consent" class="pill">Реклама дозволена</span></label></div>
      <div v-else-if="form.target_mode === 'groups'" class="recipient-grid"><label v-for="group in groups" :key="group.id" class="recipient-option"><input v-model="form.client_group_ids" type="checkbox" :value="group.id" /><span><strong>{{ group.name }}</strong><small>{{ group.client_ids.length }} клієнтів</small></span></label><p v-if="!groups.length">Спочатку створіть доступну вам групу клієнтів.</p></div>
      <p v-else>Буде використано всі неархівні анкети, до яких ви маєте доступ. Однакові email автоматично об’єднаються.</p>
    </fieldset>

    <label>Вкладення<input type="file" multiple accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg,.zip" @change="newFiles = [...$event.target.files]" /><small>PDF, DOCX, XLSX, PNG, JPG або ZIP; разом до 10 МБ.</small></label>
    <ul v-if="newFiles.length" class="file-list"><li v-for="file in newFiles" :key="file.name">{{ file.name }} — {{ Math.ceil(file.size / 1024) }} КБ</li></ul>
    <div class="actions composer-actions"><button type="button" :disabled="sending" @click="saveCampaign(false)">Зберегти чернетку</button><button type="button" :disabled="sending" @click="saveCampaign(true)">Надіслати зараз</button><button type="button" class="secondary" @click="previewOpen = !previewOpen">{{ previewOpen ? 'Закрити перегляд' : 'Попередній перегляд' }}</button><button type="button" class="secondary" @click="savePersonalTemplate">Зберегти як мій шаблон</button></div>
    <iframe v-if="previewOpen" class="email-preview" sandbox="" :srcdoc="previewDocument" title="Попередній перегляд листа" />
  </section>

  <p v-if="error" class="error">{{ error }}</p>

  <section class="section-block">
    <div class="section-heading"><div><h2>Історія розсилок</h2><p>Після постановки в чергу запис і вкладення не видаляються.</p></div></div>
    <div class="campaign-list">
      <details v-for="item in campaigns" :key="item.id" class="panel campaign-card">
        <summary><span><span class="pill" :class="`status-${item.status}`">{{ statusLabels[item.status] || item.status }}</span><strong>{{ item.subject }}</strong><small>{{ new Date(item.created_at).toLocaleString('uk-UA') }} · {{ item.from_email }}</small></span><span class="campaign-counts">{{ item.sent_count }}/{{ item.total_recipients }} надіслано</span></summary>
        <div class="campaign-details"><div><h3>Текст листа</h3><div class="email-body" v-html="item.html_body" /></div><div><h3>Результати</h3><p>Надіслано: {{ item.sent_count }} · Помилки: {{ item.failed_count }} · Пропущено: {{ item.skipped_count }}</p><ul><li v-for="recipient in item.recipients" :key="recipient.id">{{ recipient.display_name }} — {{ recipient.email }}: {{ recipient.status }}<small v-if="recipient.error_message">{{ recipient.error_message }}</small></li></ul></div></div>
        <div v-if="item.attachments.length"><strong>Вкладення:</strong> {{ item.attachments.map(file => file.original_name).join(', ') }}</div>
        <div v-if="item.status === 'draft'" class="actions"><button class="small secondary" @click.prevent="editDraft(item)">Редагувати</button><button class="small danger" @click.prevent="deleteDraft(item)">Видалити чернетку</button></div>
      </details>
      <p v-if="!campaigns.length" class="empty panel">Розсилок поки немає.</p>
    </div>
  </section>

  <section class="panel section-block">
    <div class="section-heading"><div><h2>Мої шаблони</h2><p>Особисті шаблони бачите лише ви.</p></div></div>
    <div class="simple-list"><div v-for="item in templates.filter(t => t.scope === 'personal')" :key="item.id" class="list-row"><span><strong>{{ item.name }}</strong><small>{{ item.subject }}</small></span><button class="small danger" @click="deletePersonalTemplate(item)">Видалити</button></div><p v-if="!templates.some(t => t.scope === 'personal')" class="empty">Особистих шаблонів поки немає.</p></div>
  </section>
</template>
