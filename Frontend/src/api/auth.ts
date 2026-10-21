import { API_BASE, api, ensureCsrf } from './client'
import type { User, UserSettings } from './types'

export const authApi = {
  csrf: () => ensureCsrf(true),
  me: (signal?: AbortSignal) => api.get<User>('/auth/me/', { signal }),
  register: (data: { name: string; email: string; password: string }) => api.post<User>('/auth/register/', data),
  login: (data: { email: string; password: string }) => api.post<User>('/auth/login/', data),
  logout: () => api.post<void>('/auth/logout/'),
  updateMe: (data: Partial<Pick<User, 'name' | 'email' | 'bio'>>) => api.patch<User>('/auth/me/', data),
  deleteAccount: (password: string) => api.del('/auth/me/', { password }),
  changePassword: (old_password: string, new_password: string) => api.post<void>('/auth/password/', { old_password, new_password }),
  uploadAvatar: (file: File) => {
    const form = new FormData()
    form.append('avatar', file)
    return api.upload<User>('/auth/me/avatar/', form)
  },
  removeAvatar: () => api.del<User>('/auth/me/avatar/'),
  avatarUrl: (user: Pick<User, 'avatar_version'>) => `${API_BASE}/auth/me/avatar/?v=${user.avatar_version}`,
  settings: () => api.get<UserSettings>('/settings/'),
  updateSettings: (data: Partial<UserSettings>) => api.patch<UserSettings>('/settings/', data),
}
