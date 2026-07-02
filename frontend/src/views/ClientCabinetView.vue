<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const client = ref(null)
const form = reactive({})
const editing = ref(false)
const error = ref('')
const message = ref('')
const marketingConsent = ref(false)

async function load() {
  try { client.value = await api('/clients/mine/'); Object.assign(form, client.value); marketingConsent.value = client.value.marketing_email_consent }
  catch (e) { error.value = e.message }
}
async function saveEmailPreference() {
  error.value = ''; message.value = ''
  try {
    const result = await api('/clients/email-preferences/', { method: 'PATCH', body: JSON.stringify({ marketing_email_consent: marketingConsent.value }) })
    marketingConsent.value = result.marketing_email_consent
    client.value.marketing_email_consent = result.marketing_email_consent
    message.value = 'Налаштування розсилок оновлено.'
  } catch (e) { error.value = e.message }
}
async function save() {
  error.value = ''; message.value = ''
  const allowed = [
    'client_type', 'first_name', 'last_name', 'company_name', 'contact_person', 'email', 'phone', 'website',
    'country', 'city', 'address', 'preferred_contact', 'business_description', 'requested_service',
    'project_request', 'desired_deadline', 'estimated_budget',
  ]
  const payload = Object.fromEntries(allowed.map((key) => [key, form[key]]))
  try {
    client.value = await api(`/clients/${client.value.id}/`, { method: 'PATCH', body: JSON.stringify(payload) })
    Object.assign(form, client.value); editing.value = false; message.value = 'Анкету оновлено.'
  } catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <div v-if="client">
    <header class="page-header"><div><p class="eyebrow">ОСОБИСТИЙ КАБІНЕТ</p><h1>{{ client.display_name }}</h1><p>Ваша анкета та поточна інформація про проєкт.</p></div><button @click="editing = !editing">{{ editing ? 'Скасувати' : 'Редагувати анкету' }}</button></header>
    <p v-if="message" class="success">{{ message }}</p><p v-if="error" class="error">{{ error }}</p>
    <form v-if="editing" class="panel grid two" @submit.prevent="save">
      <label>Email<input v-model="form.email" type="email" required /></label><label>Телефон<input v-model="form.phone" required /></label>
      <template v-if="form.client_type === 'person'"><label>Ім’я<input v-model="form.first_name" /></label><label>Прізвище<input v-model="form.last_name" /></label></template>
      <template v-else><label>Компанія<input v-model="form.company_name" /></label><label>Контактна особа<input v-model="form.contact_person" /></label></template>
      <label>Країна<input v-model="form.country" /></label><label>Місто<input v-model="form.city" /></label><label>Адреса<input v-model="form.address" /></label><label>Вебсайт<input v-model="form.website" /></label>
      <label>Потрібна послуга<input v-model="form.requested_service" /></label><label>Бажаний термін<input v-model="form.desired_deadline" type="date" /></label>
      <label class="span-two">Опис запиту<textarea v-model="form.project_request" rows="4" /></label><button>Зберегти</button>
    </form>
    <section v-else class="detail-grid">
      <article class="panel"><h2>Стан проєкту</h2><div class="progress"><span :style="{ width: `${client.project_progress}%` }" /></div><strong class="progress-label">{{ client.project_progress }}%</strong><dl><dt>Статус</dt><dd>{{ client.status }}</dd><dt>Оновлення</dt><dd>{{ client.project_status_note || 'Відповідальний працівник ще не додав оновлення.' }}</dd></dl></article>
      <article class="panel"><h2>Відповідальні працівники</h2><div v-for="employee in client.responsible_employees" :key="employee.id" class="contact-card"><strong>{{ employee.first_name }} {{ employee.last_name }}</strong><small>{{ employee.position }}</small><a :href="`mailto:${employee.email}`">{{ employee.email }}</a><span>{{ employee.phone }}</span></div><p v-if="!client.responsible_employees.length">Працівника ще не призначено.</p></article>
      <article class="panel span-two"><h2>Моя анкета</h2><dl class="columns"><dt>Email</dt><dd>{{ client.email }}</dd><dt>Телефон</dt><dd>{{ client.phone }}</dd><dt>Послуга</dt><dd>{{ client.requested_service }}</dd><dt>Запит</dt><dd class="preline">{{ client.project_request }}</dd></dl></article>
      <article class="panel span-two"><h2>Email-розсилки</h2><p>Службові повідомлення щодо вашого проєкту надсилаються незалежно від цього налаштування.</p><label class="checkbox consent-line"><input v-model="marketingConsent" type="checkbox" /> Я погоджуюся отримувати рекламні та інформаційні листи.</label><button class="preference-button" @click="saveEmailPreference">Зберегти налаштування</button></article>
    </section>
  </div>
  <p v-else-if="error" class="error">{{ error }}</p>
</template>
