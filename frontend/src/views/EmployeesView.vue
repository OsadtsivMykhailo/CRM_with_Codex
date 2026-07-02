<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const employees = ref([])
const error = ref('')
const showForm = ref(false)
const editingId = ref(null)
const emptyForm = () => ({
  username: '', password: '', email: '', first_name: '', last_name: '', position: '', department: '',
  phone: '', work_phone: '', middle_name: '', start_date: '', is_active: true,
})
const form = reactive(emptyForm())

async function load() {
  try { employees.value = await api('/auth/employees/') }
  catch (e) { error.value = e.message }
}

function openCreate() {
  Object.assign(form, emptyForm())
  editingId.value = null
  showForm.value = true
}

function openEdit(item) {
  Object.assign(form, emptyForm(), item, { password: '', start_date: item.start_date || '' })
  editingId.value = item.id
  showForm.value = true
}

async function save() {
  error.value = ''
  const fields = [
    'username', 'password', 'email', 'first_name', 'last_name', 'middle_name', 'position', 'department',
    'phone', 'work_phone', 'start_date', 'is_active',
  ]
  const payload = Object.fromEntries(fields.map((key) => [key, form[key]]))
  if (!payload.password) delete payload.password
  if (!payload.start_date) payload.start_date = null
  try {
    if (editingId.value) {
      await api(`/auth/employees/${editingId.value}/`, { method: 'PATCH', body: JSON.stringify(payload) })
    } else {
      await api('/auth/employees/', { method: 'POST', body: JSON.stringify(payload) })
    }
    showForm.value = false
    await load()
  } catch (e) { error.value = e.message }
}

async function deactivate(item) {
  if (!window.confirm(`Деактивувати акаунт @${item.username}? Історія дій збережеться.`)) return
  try { await api(`/auth/employees/${item.id}/`, { method: 'DELETE' }); await load() }
  catch (e) { error.value = e.message }
}

onMounted(load)
</script>

<template>
  <header class="page-header">
    <div><p class="eyebrow">КОМАНДА</p><h1>Працівники</h1><p>Деактивація забороняє вхід, але зберігає історію.</p></div>
    <button @click="openCreate">+ Новий працівник</button>
  </header>
  <form v-if="showForm" class="panel grid two" @submit.prevent="save">
    <h2 class="span-two">{{ editingId ? 'Редагування працівника' : 'Новий працівник' }}</h2>
    <label>Логін<input v-model="form.username" required /></label>
    <label>Пароль<input v-model="form.password" type="password" :required="!editingId" minlength="8" :placeholder="editingId ? 'Залиште порожнім без зміни' : ''" /></label>
    <label>Корпоративний email<input v-model="form.email" type="email" required /></label>
    <label>Ім’я<input v-model="form.first_name" required /></label>
    <label>По батькові<input v-model="form.middle_name" /></label>
    <label>Прізвище<input v-model="form.last_name" required /></label>
    <label>Посада<input v-model="form.position" required /></label>
    <label>Відділ<input v-model="form.department" required /></label>
    <label>Особистий телефон<input v-model="form.phone" /></label>
    <label>Робочий телефон<input v-model="form.work_phone" /></label>
    <label>Дата початку роботи<input v-model="form.start_date" type="date" /></label>
    <label v-if="editingId" class="checkbox"><input v-model="form.is_active" type="checkbox" /> Акаунт активний</label>
    <div class="span-two actions"><button>Зберегти</button><button type="button" class="secondary" @click="showForm = false">Скасувати</button></div>
  </form>
  <p v-if="error" class="error">{{ error }}</p>
  <div class="table-wrap">
    <table><thead><tr><th>Працівник</th><th>Посада</th><th>Відділ</th><th>Статус</th><th></th></tr></thead>
      <tbody>
        <tr v-for="item in employees" :key="item.id">
          <td><strong>{{ item.first_name }} {{ item.last_name }}</strong><small>@{{ item.username }} · {{ item.email }}</small></td>
          <td>{{ item.position }}</td><td>{{ item.department }}</td>
          <td><span class="pill" :class="{ muted: !item.is_active }">{{ item.is_active ? 'Активний' : 'Деактивований' }}</span></td>
          <td class="row-actions"><button class="small secondary" @click="openEdit(item)">Редагувати</button><button v-if="item.is_active" class="small danger" @click="deactivate(item)">Деактивувати</button></td>
        </tr>
        <tr v-if="!employees.length"><td colspan="5" class="empty">Працівників поки немає.</td></tr>
      </tbody>
    </table>
  </div>
</template>
