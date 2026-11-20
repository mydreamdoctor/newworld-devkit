/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 */

#include "NWLightingEditorModule.h"
#include "Editor/EditorNWEnvironmentComponent.h"

namespace NWLighting
{
    NWLightingEditorModule::NWLightingEditorModule()
    {
        m_descriptors.insert(m_descriptors.end(), {
            EditorNWEnvironmentComponent::CreateDescriptor(),
        });
    }

    AZ::ComponentTypeList NWLightingEditorModule::GetRequiredSystemComponents() const
    {
        return AZ::ComponentTypeList{};
    }
}

#if defined(O3DE_GEM_NAME)
AZ_DECLARE_MODULE_CLASS(AZ_JOIN(Gem_, O3DE_GEM_NAME, _Editor), NWLighting::NWLightingEditorModule)
#else
AZ_DECLARE_MODULE_CLASS(Gem_NWLighting_Editor, NWLighting::NWLightingEditorModule)
#endif
