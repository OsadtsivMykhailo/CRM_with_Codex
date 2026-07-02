<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const employees = ref([])
const senders = ref([])
const error = ref('')
const message = ref('')
const senderId = ref(null)
const form = reactive({ name: '', email: '', allowed_employee_ids: [], is_active: true })

async function load() {
  try { [employees.value, senders.value] = await Promise.all([api('/auth/employees/'), api('/shared-senders/')]) }
  catch (e) { error.value = e.message }
}
function reset() { senderId.value = null; Object.assign(form, { name: '', email: '', allowed_employee_ids: [], is_active: true }) }
function edit(item) { senderId.value = item.id; Object.assign(form, { ...item, allowed_employee_ids: [...(item.allowed_employee_ids || [])] }) }
async function save() {
  error.value = ''; message.value = ''
  try {
    const path = senderId.value ? `/shared-senders/${senderId.value}/` : '/shared-senders/'
    await api(path, { method: senderId.value ? 'PATCH' : 'POST', body: JSON.stringify(form) })
    reset(); await load(); message.value = 'Загальну адресу збережено.'
  } catch (e) { error.value = e.message }
}
onMounted(load)
</script>

<template>
  <header class="page-header"><div><RouterLink to="/email-settings">← До Email-налаштувань</RouterLink><p class="eyebrow">КОРПОРАТИВНА ПОШТА</p><h1>Загальні адреси</h1><p>Працівник побачить лише дозволені йому адреси.</p></div></header>
  <p v-if="message" class="success">{{ message }}</p><p v-if="error" class="error">{{ error }}</p>
  <section class="panel section-block">
    <form class="grid two compact-form" @submit.prevent="save">
      <label>Назва<input v-model="form.name" required placeholder="Multisoft Sales" /></label><label>Email<input v-model="form.email" type="email" required placeholder="sales@company.com" /></label>
      <fieldset class="span-two checkbox-grid"><legend>Дозволені працівники</legend><label v-for="employee in employees.filter(e => e.is_active)" :key="employee.user_id" class="checkbox"><input v-model="form.allowed_employee_ids" type="checkbox" :value="employee.user_id" /> {{ employee.first_name }} {{ employee.last_name }} (@{{ employee.username }})</label></fieldset>
      <label v-if="senderId" class="checkbox"><input v-model="form.is_active" type="checkbox" /> Адреса активна</label>
      <div class="span-two actions"><button>{{ senderId ? 'Оновити' : 'Додати адресу' }}</button><button v-if="senderId" type="button" class="secondary" @click="reset">Скасувати</button></div>
    </form>
    <div class="simple-list"><button v-for="item in senders" :key="item.id" type="button" class="list-row" @click="edit(item)"><span><strong>{{ item.name }}</strong><small>{{ item.email }}</small></span><span class="pill" :class="{ muted: !item.is_active }">{{ item.is_active ? 'Активна' : 'Неактивна' }}</span></button></div>
  </section>
</template>
