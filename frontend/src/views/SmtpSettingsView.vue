<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const settings = reactive({ name: '', company_name: 'Multisoft Velari', host: '', port: 1025, username: '', password: '', use_tls: false, use_ssl: false, is_active: true })
const error = ref('')
const message = ref('')

async function load() {
  try { Object.assign(settings, await api('/email-settings/'), { password: '' }) }
  catch (e) { error.value = e.message }
}
async function saveSettings() {
  error.value = ''; message.value = ''
  const payload = { ...settings }
  delete payload.has_password; delete payload.updated_at
  if (!payload.password) delete payload.password
  try {
    Object.assign(settings, await api('/email-settings/', { method: 'PATCH', body: JSON.stringify(payload) }), { password: '' })
    message.value = 'SMTP-налаштування збережено.'
  } catch (e) { error.value = e.message }
}
async function testSettings() {
  error.value = ''; message.value = ''
  try { message.value = (await api('/email-settings/test/', { method: 'POST', body: '{}' })).detail }
  catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <header class="page-header"><div><RouterLink to="/email-settings">← До Email-налаштувань</RouterLink><p class="eyebrow">КОРПОРАТИВНА ПОШТА</p><h1>SMTP-сервер</h1><p>Єдине поштове підключення для всієї CRM.</p></div></header>
  <p v-if="message" class="success">{{ message }}</p><p v-if="error" class="error">{{ error }}</p>
  <section class="panel section-block">
    <div class="section-heading"><div><h2>Підключення</h2><p>Для локальної роботи: 127.0.0.1:1025 (Mailpit), без логіна, TLS та SSL.</p></div><span class="pill">Пароль: {{ settings.has_password ? 'збережено' : 'не задано' }}</span></div>
    <form class="grid two" @submit.prevent="saveSettings">
      <label>Назва налаштування<input v-model="settings.name" required /></label><label>Компанія-відправник<input v-model="settings.company_name" required /><small>Використовується у змінній <code v-pre>{{Company}}</code>.</small></label>
      <label>Сервер<input v-model="settings.host" required /></label><label>Порт<input v-model.number="settings.port" type="number" min="1" max="65535" required /></label>
      <label>Логін<input v-model="settings.username" /></label><label>Новий пароль або API-ключ<input v-model="settings.password" type="password" placeholder="Залиште порожнім, щоб не змінювати" /></label>
      <label class="checkbox"><input v-model="settings.use_tls" type="checkbox" /> TLS</label><label class="checkbox"><input v-model="settings.use_ssl" type="checkbox" /> SSL</label>
      <label class="checkbox"><input v-model="settings.is_active" type="checkbox" /> Сервер активний</label>
      <div class="span-two actions"><button>Зберегти</button><button type="button" class="secondary" @click="testSettings">Перевірити підключення</button></div>
    </form>
  </section>
</template>
