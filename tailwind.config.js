/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/templates/**/*.html',
  ],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#0072e5', dark: '#005bb5', light: '#3391f0' },
        secondary: { DEFAULT: '#015e54', dark: '#013d35' },
        brand: '#1B4F8A',
      },
      fontFamily: {
        sans: ['Montserrat', 'Public Sans', 'Helvetica Neue', 'Arial', 'sans-serif'],
      }
    }
  },
  plugins: [],
}
