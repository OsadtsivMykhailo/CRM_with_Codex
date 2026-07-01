<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const client = ref(null)
const form = reactive({})
const error = ref('')
const message = ref('')
const editing = ref(false)
const deletionReason = ref('')
const showDeletion = ref(false)

async function load() {
  try { client.value = await api(`/clients/${route.params.id}/`); Object.assign(form, client.value) }
  catch (e) { error.value = e.message }
}
async function save() {
  error.value = ''; message.value = ''
  const payload = { ...form }
  ;['id', 'display_name', 'responsible_employees', 'created_at', 'updated_at', 'project_updated_at'].forEach((key) => delete payload[key])
  try {
    client.value = await api(`/clients/${route.params.id}/`, { method: 'PATCH', body: JSON.stringify(payload) })
    Object.assign(form, client.value); editing.value = false; message.value = 'Зміни збережено.'
  } catch (e) { error.value = e.message }
}
async function requestDeletion() {
  error.value = ''; message.value = ''
  try {
    await api('/deletion-requests/', { method: 'POST', body: JSON.stringify({ client_id: client.value.id, reason: deletionReason.value }) })
    showDeletion.value = false; deletionReason.value = ''; message.value = 'Запит надіслано адміністратору.'
  } catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <div v-if="client">
    <header class="page-header"><div><RouterLink to="/clients">← До списку</RouterLink><h1>{{ client.display_name }}</h1><p>Створено {{ new Date(client.created_at).toLocaleString('uk-UA') }}</p></div><div class="actions"><button @click="editing = !editing">{{ editing ? 'Закрити редагування' : 'Редагувати' }}</button><button class="danger" @click="showDeletion = !showDeletion">Запит на видалення</button></div></header>
    <p v-if="message" class="success">{{ message }}</p><p v-if="error" class="error">{{ error }}</p>
    <form v-if="editing" class="panel grid two" @submit.prevent="save">
      <label>Тип<select v-model="form.client_type"><option value="person">Фізична особа</option><option value="company">Компанія</option></select></label>
      <label v-if="form.client_type === 'company'">Назва компанії<input v-model="form.company_name" /></label>
      <template v-else><label>Ім’я<input v-model="form.first_name" /></label><label>Прізвище<input v-model="form.last_name" /></label></template>
      <label>Email<input v-model="form.email" type="email" /></label><label>Телефон<input v-model="form.phone" /></label>
      <label>Країна<input v-model="form.country" /></label><label>Місто<input v-model="form.city" /></label><label>Адреса<input v-model="form.address" /></label><label>Вебсайт<input v-model="form.website" /></label>
      <label>Послуга<input v-model="form.requested_service" /></label><label>Бажаний термін<input v-model="form.desired_deadline" type="date" /></label>
      <label>Статус<select v-model="form.status"><option value="new">Новий</option><option value="active">Активний</option><option value="paused">Призупинений</option><option value="completed">Завершений</option><option value="archived">Архівний</option></select></label>
      <label>Прогрес, %<input v-model.number="form.project_progress" type="number" min="0" max="100" /></label>
      <label class="span-two">Стан проєкту<textarea v-model="form.project_status_note" rows="3" /></label>
      <label class="span-two">Запит клієнта<textarea v-model="form.project_request" rows="4" /></label>
      <label class="span-two">Внутрішні нотатки<textarea v-model="form.internal_notes" rows="4" /></label>
      <button>Зберегти</button>
    </form>
    <form v-if="showDeletion" class="panel grid" @submit.prevent="requestDeletion">
      <h2>Запит на видалення помилкової анкети</h2><label>Причина<textarea v-model="deletionReason" minlength="10" required /></label><button class="danger">Надіслати запит</button>
    </form>
    <section v-if="!editing" class="detail-grid">
      <article class="panel"><h2>Контактні дані</h2><dl><dt>Email</dt><dd>{{ client.email }}</dd><dt>Телефон</dt><dd>{{ client.phone }}</dd><dt>Місто</dt><dd>{{ client.city }}, {{ client.country }}</dd><dt>Адреса</dt><dd>{{ client.address || '—' }}</dd></dl></article>
      <article class="panel"><h2>Проєкт</h2><dl><dt>Послуга</dt><dd>{{ client.requested_service }}</dd><dt>Статус</dt><dd>{{ client.status }}</dd><dt>Прогрес</dt><dd>{{ client.project_progress }}%</dd><dt>Поточний стан</dt><dd>{{ client.project_status_note || 'Ще не вказано' }}</dd></dl></article>
      <article class="panel span-two"><h2>Запит клієнта</h2><p class="preline">{{ client.project_request }}</p><h3>Внутрішні нотатки</h3><p class="preline">{{ client.internal_notes || 'Немає' }}</p></article>
    </section>
  </div>
  <p v-else-if="error" class="error">{{ error }}</p>
</template>
