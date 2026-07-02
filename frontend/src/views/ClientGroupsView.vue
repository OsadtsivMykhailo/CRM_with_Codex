<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, auth } from '../api'

const role = computed(() => auth.user()?.role)
const groups = ref([])
const clients = ref([])
const employees = ref([])
const creationRequests = ref([])
const editingId = ref(null)
const adminForm = reactive({ name: '', client_ids: [], editor_ids: [] })
const requestForm = reactive({ proposed_name: '', reason: '', proposed_client_ids: [], proposed_employee_ids: [] })
const error = ref('')
const message = ref('')

async function load() {
  error.value = ''
  try {
    if (role.value === 'admin') {
      const [groupList, clientOptions, staff] = await Promise.all([
        api('/client-groups/'), api('/client-groups/client-options/'), api('/auth/employees/'),
      ])
      groups.value = groupList
      clients.value = clientOptions
      employees.value = staff.filter(item => item.is_active).map(item => ({
        id: item.user_id, username: item.username, first_name: item.first_name, last_name: item.last_name,
      }))
    } else {
      const [groupList, options, ownRequests] = await Promise.all([
        api('/client-groups/'), api('/client-group-creation-requests/options/'), api('/client-group-creation-requests/'),
      ])
      groups.value = groupList
      clients.value = options.clients
      employees.value = options.employees
      creationRequests.value = ownRequests
    }
  } catch (e) { error.value = e.message }
}

function resetAdminForm() {
  editingId.value = null
  Object.assign(adminForm, { name: '', client_ids: [], editor_ids: [] })
}
function edit(item) {
  if (role.value !== 'admin') return
  editingId.value = item.id
  Object.assign(adminForm, { name: item.name, client_ids: [...item.client_ids], editor_ids: [...item.editor_ids] })
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
async function saveGroup() {
  error.value = ''; message.value = ''
  try {
    const path = editingId.value ? `/client-groups/${editingId.value}/` : '/client-groups/'
    await api(path, { method: editingId.value ? 'PATCH' : 'POST', body: JSON.stringify(adminForm) })
    message.value = editingId.value ? 'Групу оновлено.' : 'Групу створено.'
    resetAdminForm(); await load()
  } catch (e) { error.value = e.message }
}
async function requestGroupCreation() {
  error.value = ''; message.value = ''
  try {
    await api('/client-group-creation-requests/', { method: 'POST', body: JSON.stringify(requestForm) })
    Object.assign(requestForm, { proposed_name: '', reason: '', proposed_client_ids: [], proposed_employee_ids: [] })
    message.value = 'Запит на створення групи надіслано адміністратору.'
    await load()
  } catch (e) { error.value = e.message }
}

onMounted(load)
</script>

<template>
  <header class="page-header"><div><p class="eyebrow">СЕГМЕНТАЦІЯ</p><h1>Групи клієнтів</h1><p v-if="role === 'admin'">Створюйте групи, призначайте відповідальних і керуйте складом клієнтів.</p><p v-else>Ви бачите групи, за які відповідаєте, і можете запропонувати нову.</p></div></header>
  <p v-if="message" class="success">{{ message }}</p><p v-if="error" class="error">{{ error }}</p>

  <form v-if="role === 'admin'" class="panel grid two" @submit.prevent="saveGroup">
    <h2 class="span-two">{{ editingId ? 'Редагування групи' : 'Нова група' }}</h2>
    <label class="span-two">Назва<input v-model="adminForm.name" required /></label>
    <fieldset class="checkbox-grid"><legend>Відповідальні працівники</legend><label v-for="employee in employees" :key="employee.id" class="checkbox"><input v-model="adminForm.editor_ids" type="checkbox" :value="employee.id" /> {{ employee.first_name }} {{ employee.last_name }} (@{{ employee.username }})</label></fieldset>
    <fieldset class="checkbox-grid"><legend>Клієнти</legend><label v-for="client in clients" :key="client.id" class="checkbox"><input v-model="adminForm.client_ids" type="checkbox" :value="client.id" /> {{ client.display_name }} <small>({{ client.status }})</small></label><p v-if="!clients.length">Анкет немає.</p></fieldset>
    <div class="span-two actions"><button>{{ editingId ? 'Зберегти' : 'Створити групу' }}</button><button v-if="editingId" type="button" class="secondary" @click="resetAdminForm">Скасувати</button></div>
  </form>

  <form v-else class="panel grid two" @submit.prevent="requestGroupCreation">
    <h2 class="span-two">Запит на створення групи</h2>
    <label class="span-two">Запропонована назва<input v-model="requestForm.proposed_name" required minlength="2" /></label>
    <label class="span-two">Причина<textarea v-model="requestForm.reason" required minlength="10" rows="3" /></label>
    <fieldset class="checkbox-grid"><legend>Запропоновані клієнти</legend><label v-for="client in clients" :key="client.id" class="checkbox"><input v-model="requestForm.proposed_client_ids" type="checkbox" :value="client.id" /> {{ client.display_name }}</label></fieldset>
    <fieldset class="checkbox-grid"><legend>Запропоновані відповідальні</legend><label v-for="employee in employees" :key="employee.id" class="checkbox"><input v-model="requestForm.proposed_employee_ids" type="checkbox" :value="employee.id" /> {{ employee.first_name }} {{ employee.last_name }} (@{{ employee.username }})</label></fieldset>
    <p class="span-two">Після схвалення ви також автоматично станете відповідальним за групу.</p>
    <button>Надіслати запит</button>
  </form>

  <section class="cards group-cards">
    <article v-for="item in groups" :key="item.id" :class="{ clickable: role === 'admin' }" @click="edit(item)"><span class="pill">{{ item.client_ids.length }} клієнтів</span><h2>{{ item.name }}</h2><small>Відповідальних працівників: {{ item.editor_ids.length }}</small></article>
    <p v-if="!groups.length" class="empty panel">Доступних груп поки немає.</p>
  </section>

  <section v-if="role === 'employee' && creationRequests.length" class="section-block">
    <h2>Мої запити на створення</h2>
    <div class="simple-list"><div v-for="item in creationRequests" :key="item.id" class="list-row"><span><strong>{{ item.proposed_name }}</strong><small>{{ item.reason }}</small><small v-if="item.decision_note">Рішення: {{ item.decision_note }}</small></span><span class="pill">{{ item.status }}</span></div></div>
  </section>
</template>
