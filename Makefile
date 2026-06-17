# Checks to see if the required copyright header is in every file
check-copyright:
	@echo "🔍 Checking for required copyright header..."
	@missing_files=$$(find src tests \
		\( -name '__pycache__' \) -prune -o \
		-name '*.py' -print | \
		xargs grep -L "Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors" || true); \
	if [ -n "$$missing_files" ]; then \
		echo "❌ The following files are missing the required copyright header:"; \
		echo "$$missing_files"; \
		exit 1; \
	else \
		echo "✅ All files contain the required header."; \
	fi

# Adds copyright statement to the top of files that need it
add-copyright:
	@find src tests -name '*.py' ! -path '*/__pycache__/*' | while read -r f; do \
		if ! grep -q "Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors" "$$f"; then \
			tmp="$$(mktemp)"; \
			{ \
				head_line="$$(head -n 1 "$$f")"; \
				if [ "$$head_line" = '#!'* ]; then \
					head -n 1 "$$f"; \
					printf '%s\n%s\n\n' \
						'# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors' \
						'# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception'; \
					tail -n +2 "$$f"; \
				else \
					printf '%s\n%s\n\n' \
						'# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors' \
						'# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception'; \
					cat "$$f"; \
				fi; \
			} > "$$tmp" && mv "$$tmp" "$$f"; \
			echo "Updated $$f"; \
		fi; \
	done
